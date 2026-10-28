"""Branch reviews: starting one on a requirement's branch, running it, and what it leaves (with
Codex faked)."""

import asyncio
import os
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import claude, codex, repositories, reviews, tasks
from repocop.services.codex import CodexError
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement
from repocop.services.reviews import ReviewError
from repocop.services.runner import CHANGED_WORKTREE, TaskRunner
from repocop.services.tasks import Status, Task, TaskError
from tests.conftest import kill_process, process_gone, recorded_requirement, run_git
from tests.fakes.fake_claude import FakeClaudeFactory
from tests.fakes.fake_codex import FakeCodex


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    repository = repositories.register(
        conn, settings, str(remote_repo), default_branch="main"
    ).repository
    for name in ("implement", "address-review"):
        folder = repository.primary_path / ".claude" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=repository.primary_path)
    run_git("commit", "-qm", "Add skills", cwd=repository.primary_path)
    return repository


@pytest.fixture
def requirement(conn: sqlite3.Connection, settings: Settings, repo: Repository) -> Requirement:
    """bulk-user-import, with no branch yet."""
    return recorded_requirement(conn, settings, repo)


@pytest.fixture
def worktree(conn: sqlite3.Connection, settings: Settings, requirement: Requirement) -> Path:
    """bulk-user-import's worktree, after a first task that is over and left one commit on its
    branch."""
    first = tasks.start(conn, settings, requirement, "implement")
    tasks.cancel(conn, first)
    assert first.worktree_path is not None
    commit_in(first.worktree_path)
    return first.worktree_path


def commit_in(folder: Path, name: str = "work.txt") -> str:
    (folder / name).write_text("work\n")
    run_git("add", name, cwd=folder)
    run_git("commit", "-qm", f"Add {name}", cwd=folder)
    return run_git("rev-parse", "HEAD", cwd=folder)


async def until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def stored(conn: sqlite3.Connection, task_id: int) -> Task:
    task = tasks.get(conn, task_id)
    assert task is not None
    return task


def review_tasks(conn: sqlite3.Connection, requirement: Requirement) -> list[Task]:
    return [t for t in tasks.list_for_requirement(conn, requirement) if reviews.is_review(t)]


async def run_review(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    fake_claude: FakeClaudeFactory,
) -> Task:
    """Start a review and wait until it is over."""
    task = reviews.start(conn, settings, requirement)
    TaskRunner(settings, fake_claude).run(task.id)
    await until(lambda: stored(conn, task.id).status not in tasks.ACTIVE)
    return stored(conn, task.id)


# ---------------------------------------------------------------- starting a review


def test_start_queues_a_review_in_the_requirements_worktree(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
) -> None:
    task = reviews.start(conn, settings, requirement)
    assert task.workflow == reviews.WORKFLOW and task.status is Status.QUEUED
    assert task.worktree_path == worktree and task.branch == "agent/bulk-user-import"
    assert fake_codex.reviews == []  # nothing runs until the runner starts it


def test_start_is_refused_before_the_requirements_first_task(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, fake_codex: FakeCodex
) -> None:
    with pytest.raises(ReviewError, match="has no branch yet"):
        reviews.start(conn, settings, requirement)


def test_start_is_refused_while_another_task_is_active(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, fake_codex: FakeCodex
) -> None:
    tasks.start(conn, settings, requirement, "implement")
    with pytest.raises(TaskError, match=r"task #1 \(implement\) is still queued"):
        reviews.start(conn, settings, requirement)


@pytest.mark.usefixtures("worktree")
def test_start_is_refused_when_codex_is_not_installed(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", os.defpath)
    with pytest.raises(CodexError, match="isn't installed"):
        reviews.start(conn, settings, requirement)
    assert review_tasks(conn, requirement) == []


@pytest.mark.usefixtures("worktree")
def test_start_is_refused_when_codex_is_signed_out(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, fake_codex: FakeCodex
) -> None:
    fake_codex.log_out()
    with pytest.raises(CodexError, match="isn't signed in"):
        reviews.start(conn, settings, requirement)
    assert review_tasks(conn, requirement) == []


@pytest.mark.usefixtures("worktree", "fake_codex")
def test_start_is_refused_when_the_base_was_never_fetched(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, repo: Repository
) -> None:
    run_git("update-ref", "-d", "refs/remotes/origin/main", cwd=repo.primary_path)
    with pytest.raises(ReviewError, match=r"origin/main isn't in sample's checkout\. Fetch it"):
        reviews.start(conn, settings, requirement)


@pytest.mark.usefixtures("fake_codex")
def test_start_is_refused_with_uncommitted_changes_in_the_worktree(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, worktree: Path
) -> None:
    (worktree / "draft.txt").write_text("not committed\n")
    with pytest.raises(ReviewError, match=r"uncommitted changes \(draft.txt\)"):
        reviews.start(conn, settings, requirement)


@pytest.mark.usefixtures("fake_codex")
def test_start_is_refused_when_the_branch_has_no_commits_of_its_own(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    repo: Repository,
) -> None:
    head = run_git("rev-parse", "HEAD", cwd=worktree)
    run_git("update-ref", "refs/remotes/origin/main", head, cwd=repo.primary_path)
    with pytest.raises(ReviewError, match="nothing to review"):
        reviews.start(conn, settings, requirement)


# ---------------------------------------------------------------- running a review


async def test_a_review_completes_with_codexs_output_the_review_and_the_commit(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    fake_codex.review_says("- [P2] Close the file")
    head = run_git("rev-parse", "HEAD", cwd=worktree)
    task = await run_review(conn, settings, requirement, fake_claude)
    assert task.status is Status.COMPLETED and task.error is None
    events = tasks.events_after(conn, task.id, 0)
    assert [e.kind for e in events[:2]] == ["status_change", "status_change"]
    output = [e for e in events if e.kind == "command_output"]
    assert output and "sandbox: read-only" in output[0].payload["text"]
    assert events[-2].kind == "assistant_text"
    assert events[-2].payload == {"text": "- [P2] Close the file", "who": "Codex"}
    assert events[-1].payload == {"status": "completed", "review": {"commit": head}}
    (call,) = fake_codex.reviews
    assert call["cwd"] == str(worktree) and "--base=origin/main" in call["args"]
    assert fake_claude.clients == []  # no Claude session is opened for a review
    assert task.session_pid is None


async def test_a_failed_review_fails_its_task_with_codexs_reason(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    fake_codex.fail_with("The 'x' model is not supported")
    task = await run_review(conn, settings, requirement, fake_claude)
    assert task.status is Status.FAILED
    assert task.error == "ERROR: The 'x' model is not supported"
    assert reviews.latest(conn, settings, requirement) is None


async def test_a_review_that_leaves_the_worktree_changed_fails(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    fake_codex.leave_behind("stray.txt")
    task = await run_review(conn, settings, requirement, fake_claude)
    assert task.status is Status.FAILED and task.error == CHANGED_WORKTREE
    assert reviews.latest(conn, settings, requirement) is None


async def test_a_review_that_can_no_longer_run_fails_with_the_reason(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    task = reviews.start(conn, settings, requirement)
    fake_codex.log_out()
    TaskRunner(settings, fake_claude).run(task.id)
    await until(lambda: stored(conn, task.id).status is Status.FAILED)
    assert stored(conn, task.id).error == "Codex isn't signed in: run `codex login`"
    assert fake_codex.reviews == []


async def test_cancelling_a_review_stops_codex(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    fake_codex.hang()
    task = reviews.start(conn, settings, requirement)
    runner = TaskRunner(settings, fake_claude)
    runner.run(task.id)
    await until(lambda: fake_codex.started and stored(conn, task.id).session_pid is not None)
    pid = stored(conn, task.id).session_pid
    assert pid is not None
    await runner.cancel(task.id)
    after = stored(conn, task.id)
    assert after.status is Status.CANCELLED and after.session_pid is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert reviews.latest(conn, settings, requirement) is None


async def test_a_review_takes_no_instructions(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    fake_codex.hang()
    task = reviews.start(conn, settings, requirement)
    runner = TaskRunner(settings, fake_claude)
    runner.run(task.id)
    with pytest.raises(TaskError, match="is a review, which takes no instructions"):
        await runner.send(task.id, "also check the tests")
    await runner.cancel(task.id)
    assert "user_instruction" not in [e.kind for e in tasks.events_after(conn, task.id, 0)]


async def test_a_review_interrupted_by_a_restart_fails_and_can_start_again(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    task = reviews.start(conn, settings, requirement)
    tasks.transition(conn, task.id, Status.RUNNING)  # running when RepoCop stopped
    (settled,) = TaskRunner(settings, fake_claude).recover()
    assert settled.status is Status.FAILED and settled.error == tasks.RESTARTED
    again = tasks.start_again(conn, settings, settled)
    assert reviews.is_review(again) and again.worktree_path == worktree
    TaskRunner(settings, fake_claude).run(again.id)
    await until(lambda: stored(conn, again.id).status is Status.COMPLETED)


@pytest.mark.usefixtures("fake_codex")
def test_a_restart_stops_everything_a_review_left_running(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, worktree: Path
) -> None:
    task = reviews.start(conn, settings, requirement)
    tasks.transition(conn, task.id, Status.RUNNING)
    # Codex as a crashed RepoCop left it: leading its own group, with a command it ran.
    leftover = subprocess.Popen(
        ["sh", "-c", "sleep 60 & echo $!; wait"],
        cwd=worktree,
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    assert leftover.stdout is not None
    command = int(leftover.stdout.readline())
    try:
        ref = claude.process_ref(leftover.pid)
        assert ref is not None
        tasks.set_process(conn, task.id, ref.pid, ref.start)
        TaskRunner(settings).recover()
        leftover.wait(timeout=10)
        assert process_gone(command)
    finally:
        kill_process(command)


# ---------------------------------------------------------------- the latest review


def test_latest_is_none_before_any_review(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, worktree: Path
) -> None:
    assert reviews.latest(conn, settings, requirement) is None


async def test_latest_names_the_commit_reviewed_and_says_when_the_branch_moved_on(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    reviewed = run_git("rev-parse", "HEAD", cwd=worktree)
    task = await run_review(conn, settings, requirement, fake_claude)
    latest = reviews.latest(conn, settings, requirement)
    assert latest is not None
    assert (latest.task_id, latest.commit, latest.head) == (task.id, reviewed, reviewed)
    assert latest.finished_at == task.updated_at and not latest.moved_on
    newer = commit_in(worktree, "more.txt")
    moved = reviews.latest(conn, settings, requirement)
    assert moved is not None and moved.commit == reviewed and moved.head == newer
    assert moved.moved_on


async def test_latest_is_the_last_review_that_finished(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    first = await run_review(conn, settings, requirement, fake_claude)
    fake_codex.fail_with("out of credit")
    await run_review(conn, settings, requirement, fake_claude)
    latest = reviews.latest(conn, settings, requirement)
    assert latest is not None and latest.task_id == first.id


# ---------------------------------------------------------------- addressing a review


@pytest.mark.usefixtures("worktree", "fake_codex")
def test_address_is_refused_without_a_finished_review(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, repo: Repository
) -> None:
    with pytest.raises(ReviewError, match="bulk-user-import has no finished review to address"):
        reviews.address(conn, settings, requirement)


async def test_address_is_refused_when_the_repository_lacks_the_skill(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    repo: Repository,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    await run_review(conn, settings, requirement, fake_claude)
    run_git("rm", "-rq", ".claude/skills/address-review", cwd=repo.primary_path)
    run_git("commit", "-qm", "Drop the skill", cwd=repo.primary_path)
    with pytest.raises(TaskError, match="'address-review' isn't a skill committed"):
        reviews.address(conn, settings, requirement)


async def test_address_is_refused_when_the_branch_was_made_before_the_skill(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    await run_review(conn, settings, requirement, fake_claude)
    run_git("rm", "-rq", ".claude/skills/address-review", cwd=worktree)
    run_git("commit", "-qm", "As if the branch predates the skill", cwd=worktree)
    with pytest.raises(ReviewError, match="branch doesn't have the address-review skill yet"):
        reviews.address(conn, settings, requirement)


async def test_address_starts_the_skill_with_the_requirements_last_finished_review(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    repo: Repository,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    fake_codex.review_says("- [P2] Close the file\n  It is left open.")
    reviewed = run_git("rev-parse", "HEAD", cwd=worktree)
    await run_review(conn, settings, requirement, fake_claude)
    task = reviews.address(conn, settings, requirement)
    assert task.workflow == "address-review" and task.worktree_path == worktree
    TaskRunner(settings, fake_claude).run(task.id)
    await until(lambda: stored(conn, task.id).status is Status.WAITING_FOR_USER)
    handed = (
        f"Codex's review of this branch at commit {reviewed[:12]}:\n\n"
        "- [P2] Close the file\n  It is left open."
    )
    (client,) = fake_claude.clients
    assert client.prompts == [f"/address-review specs/changes/todo/bulk-user-import.md\n\n{handed}"]
    events = tasks.events_after(conn, task.id, 0)
    assert [e.payload["text"] for e in events if e.kind == "user_instruction"] == [handed]


async def test_an_addressing_task_started_again_is_given_the_review_again(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    repo: Repository,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    await run_review(conn, settings, requirement, fake_claude)
    first = tasks.cancel(conn, reviews.address(conn, settings, requirement))
    again = tasks.start_again(conn, settings, first)
    TaskRunner(settings, fake_claude).run(again.id)
    await until(lambda: stored(conn, again.id).status is Status.WAITING_FOR_USER)
    assert "Codex's review of this branch at commit" in fake_claude.clients[0].prompts[0]


async def test_no_other_task_is_handed_a_review(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
) -> None:
    await run_review(conn, settings, requirement, fake_claude)
    task = tasks.start(conn, settings, requirement, "implement")
    assert reviews.handover(conn, task) is None
    TaskRunner(settings, fake_claude).run(task.id)
    await until(lambda: stored(conn, task.id).status is Status.WAITING_FOR_USER)
    assert fake_claude.clients[0].prompts == ["/implement specs/changes/todo/bulk-user-import.md"]


async def test_address_runs_no_git_in_a_worktree_swapped_for_a_symlink(
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    worktree: Path,
    tmp_path: Path,
    fake_codex: FakeCodex,
    fake_claude: FakeClaudeFactory,
    git_calls: Callable[[], list[list[str]]],
) -> None:
    await run_review(conn, settings, requirement, fake_claude)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    run_git("init", "-q", cwd=elsewhere)
    worktree.rename(tmp_path / "moved-aside")
    worktree.symlink_to(elsewhere)
    before = len(git_calls())
    with pytest.raises(TaskError, match="is gone"):
        reviews.address(conn, settings, requirement)
    skill = ".claude/skills/address-review/SKILL.md"
    assert not any(skill in call for call in git_calls()[before:])


def test_the_review_is_by_the_reviewer_the_pages_name() -> None:
    assert reviews.REVIEWER == codex.NAME == "Codex"
