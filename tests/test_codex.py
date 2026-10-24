"""Codex: its review of a branch, run in a RepoCop worktree (with the CLI faked)."""

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import codex, repositories, worktrees
from repocop.services.codex import CodexError, Finished, Output
from repocop.services.repositories import Repository
from tests.conftest import kill_process, process_gone
from tests.fakes.fake_codex import FakeCodex

BASE = "origin/main"


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo)).repository


@pytest.fixture
def worktree(settings: Settings, repo: Repository) -> Path:
    return worktrees.create(repo, settings, "req-1-x", "feature/req-1-x").path


async def run(
    settings: Settings, repo: Repository, worktree: Path
) -> list[codex.Output | codex.Finished]:
    review = await codex.Review.start(settings, repo, worktree, base=BASE)
    try:
        return [update async for update in review.updates()]
    finally:
        await review.stop()


# ---------------------------------------------------------------- where it runs


async def test_start_refuses_the_primary_checkout(
    settings: Settings, repo: Repository, fake_codex: FakeCodex
) -> None:
    with pytest.raises(CodexError, match="isn't a RepoCop worktree"):
        await codex.Review.start(settings, repo, repo.primary_path, base=BASE)
    assert fake_codex.calls == []


async def test_start_refuses_a_folder_that_is_not_a_worktree(
    settings: Settings, repo: Repository, fake_codex: FakeCodex
) -> None:
    folder = settings.worktrees_root / repo.name / "not-a-worktree"
    folder.mkdir(parents=True)
    with pytest.raises(CodexError, match="isn't a RepoCop worktree"):
        await codex.Review.start(settings, repo, folder, base=BASE)
    assert fake_codex.calls == []


async def test_start_refuses_when_codex_is_not_installed(
    settings: Settings, repo: Repository, worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", os.defpath)
    with pytest.raises(CodexError, match="isn't installed"):
        await codex.Review.start(settings, repo, worktree, base=BASE)


# ---------------------------------------------------------------- how it runs


async def test_a_review_runs_in_the_worktree_against_the_base_with_input_closed(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    await run(settings, repo, worktree)
    (call,) = fake_codex.reviews
    assert call["args"][:2] == ["review", "--base=origin/main"]
    assert call["cwd"] == str(worktree)
    assert call["input_closed"] is True


async def test_a_review_asks_for_the_read_only_sandbox_and_never_bypasses_it(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    await run(settings, repo, worktree)
    args = fake_codex.reviews[0]["args"]
    assert 'sandbox_mode="read-only"' in args
    assert 'approval_policy="never"' in args
    assert not any("bypass" in arg or "danger" in arg for arg in args)


async def test_a_review_uses_codexs_own_model_unless_one_is_configured(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    await run(settings, repo, worktree)
    configured = settings.model_copy(update={"review_model": "gpt-6-sol"})
    await run(configured, repo, worktree)
    unset, named = (call["args"] for call in fake_codex.reviews)
    assert not any("review_model" in arg for arg in unset)
    assert 'review_model="gpt-6-sol"' in named


async def test_a_review_runs_at_the_configured_effort_which_is_high_by_default(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    await run(settings, repo, worktree)
    await run(settings.model_copy(update={"review_effort": "xhigh"}), repo, worktree)
    await run(settings.model_copy(update={"review_effort": None}), repo, worktree)
    default, named, unset = (call["args"] for call in fake_codex.reviews)
    assert 'model_reasoning_effort="high"' in default
    assert 'model_reasoning_effort="xhigh"' in named
    assert not any("model_reasoning_effort" in arg for arg in unset)


# ---------------------------------------------------------------- what it reports


async def test_a_review_yields_codexs_output_and_then_the_review(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    fake_codex.review_says("- [P2] Close the file\n  It is left open.\n")
    updates = await run(settings, repo, worktree)
    output = "".join(update.text for update in updates if isinstance(update, Output))
    assert "sandbox: read-only" in output and "git diff" in output
    assert updates[-1] == Finished("- [P2] Close the file\n  It is left open.", None)
    assert all(isinstance(update, Output) for update in updates[:-1])


async def test_a_failed_review_reports_codexs_error_and_no_review(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    fake_codex.fail_with("The 'x' model is not supported")
    updates = await run(settings, repo, worktree)
    assert updates[-1] == Finished(None, "ERROR: The 'x' model is not supported")


async def test_long_output_is_clipped(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex, "MAX_OUTPUT_TEXT", 10)
    updates = await run(settings, repo, worktree)
    first = updates[0]
    assert isinstance(first, Output) and first.text == "OpenAI Cod" + codex.CLIPPED


async def test_a_review_that_runs_too_long_is_stopped_and_says_so(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_codex.hang()
    monkeypatch.setattr(codex, "REVIEW_TIMEOUT_S", 0.5)
    updates = await asyncio.wait_for(run(settings, repo, worktree), timeout=20)
    last = updates[-1]
    assert isinstance(last, Finished) and last.review is None
    assert last.error is not None and "timed out" in last.error


async def test_stop_ends_a_running_review(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    fake_codex.hang()
    review = await codex.Review.start(settings, repo, worktree, base=BASE)
    updates = review.updates()
    await anext(updates)  # it has started
    await review.stop()
    rest = [update async for update in updates]
    last = rest[-1]
    assert isinstance(last, Finished) and last.review is None and last.error is not None
    with pytest.raises(ProcessLookupError):
        os.kill(review.pid, 0)


# ---------------------------------------------------------------- whether it can run


def test_check_ready_passes_when_codex_is_signed_in(tmp_path: Path, fake_codex: FakeCodex) -> None:
    codex.check_ready(tmp_path)
    assert fake_codex.calls == [["login", "status"]]
    assert fake_codex.records[0]["input_closed"] is True


def test_check_ready_says_how_to_sign_in(tmp_path: Path, fake_codex: FakeCodex) -> None:
    fake_codex.log_out()
    with pytest.raises(CodexError, match="isn't signed in: run `codex login`"):
        codex.check_ready(tmp_path)


def test_check_ready_reports_a_missing_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", os.defpath)
    with pytest.raises(CodexError, match="isn't installed"):
        codex.check_ready(tmp_path)


def test_the_review_workflow_can_never_be_a_skills_name() -> None:
    from repocop.services import tasks

    assert not tasks.WORKFLOW_NAME.fullmatch(codex.WORKFLOW)


# ---------------------------------------------------------------- a review that misbehaves


async def test_stop_also_ends_a_child_that_outlives_codex(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex, "STOP_GRACE_S", 0.5)
    fake_codex.leave_a_stubborn_child()
    fake_codex.hang()
    review = await codex.Review.start(settings, repo, worktree, base=BASE)
    try:
        await anext(review.updates())  # running, with its child
        await review.stop()
        assert process_gone(review.pid) and process_gone(fake_codex.child_pid)
    finally:
        kill_process(fake_codex.child_pid)


async def test_a_review_whose_process_outlives_its_progress_output_still_times_out(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex, "REVIEW_TIMEOUT_S", 1.0)
    monkeypatch.setattr(codex, "STOP_GRACE_S", 0.5)
    fake_codex.close_progress_and_wait()
    updates = await asyncio.wait_for(run(settings, repo, worktree), timeout=15)
    last = updates[-1]
    assert isinstance(last, Finished) and last.error is not None and "timed out" in last.error


async def test_a_review_whose_output_outlives_its_process_still_times_out(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex, "REVIEW_TIMEOUT_S", 1.0)
    monkeypatch.setattr(codex, "STOP_GRACE_S", 0.5)
    fake_codex.hold_output_open()
    try:
        updates = await asyncio.wait_for(run(settings, repo, worktree), timeout=15)
        last = updates[-1]
        assert isinstance(last, Finished) and last.error is not None and "timed out" in last.error
        assert process_gone(fake_codex.child_pid)  # the child holding the output was stopped too
    finally:
        kill_process(fake_codex.child_pid)


async def test_a_progress_line_longer_than_the_stream_limit_is_left_out(
    settings: Settings, repo: Repository, worktree: Path, fake_codex: FakeCodex
) -> None:
    fake_codex.print_a_long_line()
    updates = await run(settings, repo, worktree)
    assert updates[-1] == Finished("No actionable defects were found.", None)
    output = "".join(update.text for update in updates if isinstance(update, Output))
    assert codex.LEFT_OUT in output
