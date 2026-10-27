"""Runner: each task's Claude session in the background, keyed by task id (with Claude faked)."""

import asyncio
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import claude, repositories, tasks
from repocop.services.repositories import Repository
from repocop.services.runner import RESTART_REASON, TaskRunner
from repocop.services.tasks import Status, Task, TaskError
from tests.conftest import recorded_requirement, run_git
from tests.fakes.fake_claude import FakeClaudeFactory


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    repository = repositories.register(conn, settings, str(remote_repo)).repository
    for name in ("implement", "review-requirement"):
        folder = repository.primary_path / ".claude" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=repository.primary_path)
    run_git("commit", "-qm", "Add skills", cwd=repository.primary_path)
    return repository


def queue(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, name: str = "bulk-user-import"
) -> Task:
    requirement = recorded_requirement(conn, settings, repo, f"{name}.md")
    return tasks.start(conn, settings, requirement, "implement")


async def until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def status(conn: sqlite3.Connection, task_id: int) -> Status:
    task = tasks.get(conn, task_id)
    assert task is not None
    return task.status


def kinds(conn: sqlite3.Connection, task_id: int) -> list[str]:
    return [event.kind for event in tasks.events_after(conn, task_id, 0)]


def texts(conn: sqlite3.Connection, task_id: int) -> list[str]:
    return [e.payload.get("text", "") for e in tasks.events_after(conn, task_id, 0)]


# ---------------------------------------------------------------- running a task


async def test_run_takes_a_queued_task_to_waiting_for_user_with_a_transcript(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    task = queue(conn, settings, repo)
    runner = TaskRunner(settings, fake_claude)
    runner.run(task.id)
    assert status(conn, task.id) is Status.RUNNING
    await until(lambda: status(conn, task.id) is Status.WAITING_FOR_USER)
    assert kinds(conn, task.id) == [
        "status_change",
        "status_change",
        "assistant_text",
        "tool_use",
        "tool_result",
        "assistant_text",
        "status_change",
    ]
    client = fake_claude.clients[0]
    assert client.prompts == ["/implement specs/changes/todo/bulk-user-import.md"]
    assert client.cwd == task.worktree_path
    stored = tasks.get(conn, task.id)
    assert stored is not None and stored.claude_session_id == client.session_id
    assert not client.connected


async def test_run_fails_the_task_when_its_skill_is_missing_from_the_worktree(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    task = queue(conn, settings, repo)
    assert task.worktree_path is not None
    (task.worktree_path / ".claude" / "skills" / "implement" / "SKILL.md").unlink()
    TaskRunner(settings, fake_claude).run(task.id)
    await until(lambda: status(conn, task.id) is Status.FAILED)
    failed = tasks.get(conn, task.id)
    assert failed is not None and failed.error == "Unknown skill: /implement"
    assert "error" in kinds(conn, task.id)


async def test_run_fails_the_task_when_its_worktree_is_gone(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    fake_claude: FakeClaudeFactory,
    tmp_path: Path,
) -> None:
    task = queue(conn, settings, repo)
    assert task.worktree_path is not None
    task.worktree_path.rename(tmp_path / "moved-away")
    TaskRunner(settings, fake_claude).run(task.id)
    await until(lambda: status(conn, task.id) is Status.FAILED)
    failed = tasks.get(conn, task.id)
    assert failed is not None and "isn't a RepoCop worktree" in (failed.error or "")
    assert fake_claude.clients == []


# ---------------------------------------------------------------- instructions


async def test_an_instruction_to_a_waiting_task_resumes_its_session(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    task = queue(conn, settings, repo)
    runner = TaskRunner(settings, fake_claude)
    runner.run(task.id)
    await until(lambda: status(conn, task.id) is Status.WAITING_FOR_USER)
    await runner.send(task.id, "Also add tests.")
    await until(
        lambda: len(fake_claude.clients) == 2 and status(conn, task.id) is Status.WAITING_FOR_USER
    )
    first, second = fake_claude.clients
    assert second.options.resume == first.session_id
    assert second.prompts == ["Also add tests."]
    assert "Also add tests." in texts(conn, task.id)
    assert "Noted: Also add tests." in texts(conn, task.id)


async def test_an_instruction_while_running_is_answered_as_the_next_turn(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    slow = FakeClaudeFactory(delay=0.05)
    task = queue(conn, settings, repo)
    runner = TaskRunner(settings, slow)
    runner.run(task.id)
    await until(lambda: len(slow.clients) == 1)
    await runner.send(task.id, "Keep it small.")
    await until(lambda: status(conn, task.id) is Status.WAITING_FOR_USER)
    assert len(slow.clients) == 1
    assert slow.clients[0].prompts[1] == "Keep it small."
    assert texts(conn, task.id)[-2] == "Noted: Keep it small."


async def test_an_instruction_reaches_only_its_own_tasks_session(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    slow = FakeClaudeFactory(delay=0.05)
    first = queue(conn, settings, repo, name="first")
    second = queue(conn, settings, repo, name="second")
    runner = TaskRunner(settings, slow)
    runner.run(first.id)
    runner.run(second.id)
    await until(lambda: len(slow.clients) == 2)
    await runner.send(second.id, "Only for the second.")
    await until(lambda: status(conn, first.id) is Status.WAITING_FOR_USER)
    await until(lambda: status(conn, second.id) is Status.WAITING_FOR_USER)
    assert first.worktree_path is not None and second.worktree_path is not None
    by_cwd = {client.cwd: client.prompts for client in slow.clients}
    assert "Only for the second." not in by_cwd[first.worktree_path]
    assert "Only for the second." in by_cwd[second.worktree_path]
    assert "Only for the second." not in texts(conn, first.id)


async def test_an_instruction_to_a_finished_task_is_refused(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    task = queue(conn, settings, repo)
    tasks.cancel(conn, task)
    with pytest.raises(TaskError, match="cancelled"):
        await TaskRunner(settings, fake_claude).send(task.id, "Hello?")


async def test_an_empty_instruction_is_refused(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    task = queue(conn, settings, repo)
    with pytest.raises(TaskError, match="empty"):
        await TaskRunner(settings, fake_claude).send(task.id, "   ")


# ---------------------------------------------------------------- cancel and shutdown


async def test_cancel_interrupts_a_running_task(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    slow = FakeClaudeFactory(delay=0.05)
    task = queue(conn, settings, repo)
    runner = TaskRunner(settings, slow)
    runner.run(task.id)
    await until(lambda: len(slow.clients) == 1)
    await runner.cancel(task.id)
    assert status(conn, task.id) is Status.CANCELLED
    assert "[Request interrupted by user]" in texts(conn, task.id)
    await until(lambda: not slow.clients[0].connected)


async def test_cancel_of_a_waiting_task_needs_no_session(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    task = queue(conn, settings, repo)
    runner = TaskRunner(settings, fake_claude)
    runner.run(task.id)
    await until(lambda: status(conn, task.id) is Status.WAITING_FOR_USER)
    await runner.cancel(task.id)
    assert status(conn, task.id) is Status.CANCELLED
    assert len(fake_claude.clients) == 1


async def test_shutdown_closes_sessions_and_leaves_status_for_recovery(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    slow = FakeClaudeFactory(delay=0.2)
    task = queue(conn, settings, repo)
    runner = TaskRunner(settings, slow)
    runner.run(task.id)
    await until(lambda: len(slow.clients) == 1)
    await runner.shutdown()
    assert status(conn, task.id) is Status.RUNNING
    assert not slow.clients[0].connected


async def test_a_session_on_the_wrong_credential_fails_its_task_with_the_reason(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    keyed = FakeClaudeFactory(api_key_source="ANTHROPIC_API_KEY")
    task = queue(conn, settings, repo)
    TaskRunner(settings, keyed).run(task.id)
    await until(lambda: status(conn, task.id) is Status.FAILED)
    failed = tasks.get(conn, task.id)
    assert failed is not None and "not your subscription" in (failed.error or "")
    await until(lambda: not keyed.clients[0].connected)


async def test_run_records_the_session_process_while_it_runs_and_clears_it_after(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    factory = FakeClaudeFactory(delay=0.05, process="exits")
    task = queue(conn, settings, repo)
    TaskRunner(settings, factory).run(task.id)
    await until(lambda: (tasks.get(conn, task.id) or task).session_pid is not None)
    stand_in = factory.clients[0].process
    assert stand_in is not None and (tasks.get(conn, task.id) or task).session_pid == stand_in.pid
    await until(lambda: status(conn, task.id) is Status.WAITING_FOR_USER)
    await until(lambda: (tasks.get(conn, task.id) or task).session_pid is None)


# ---------------------------------------------------------------- restart recovery (ADR-010)


def last_status_change(conn: sqlite3.Connection, task_id: int) -> dict[str, object]:
    event = tasks.events_after(conn, task_id, 0)[-1]
    assert event.kind == "status_change"
    return event.payload


def test_recover_lets_a_resumable_task_wait_and_records_where_it_stopped(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queue(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    tasks.set_session(conn, task.id, "session-1")
    assert task.worktree_path is not None
    (task.worktree_path / "half.txt").write_text("half done\n")
    TaskRunner(settings).recover()
    assert status(conn, task.id) is Status.WAITING_FOR_USER
    assert last_status_change(conn, task.id)["interrupted"] == {
        "reason": RESTART_REASON,
        "commits": 0,
        "uncommitted": ["half.txt"],
        "stopped_process": None,
    }


def test_recover_fails_a_running_task_without_a_session(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queue(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    TaskRunner(settings).recover()
    failed = tasks.get(conn, task.id)
    assert failed is not None and (failed.status, failed.error) == (
        Status.FAILED,
        "app_restarted",
    )
    assert "interrupted" in last_status_change(conn, task.id)


def test_recover_fails_a_task_that_never_started(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queue(conn, settings, repo)
    TaskRunner(settings).recover()
    assert status(conn, task.id) is Status.FAILED


def test_recover_stops_a_session_process_left_behind(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queue(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    leftover = subprocess.Popen(["sleep", "60"], cwd=task.worktree_path)
    ref = claude.process_ref(leftover.pid)
    assert ref is not None
    tasks.set_process(conn, task.id, ref.pid, ref.start)
    TaskRunner(settings).recover()
    leftover.wait(timeout=10)
    assert last_status_change(conn, task.id)["interrupted"]["stopped_process"] == leftover.pid  # type: ignore[index]
    recovered = tasks.get(conn, task.id)
    assert recovered is not None and recovered.session_pid is None


def test_recover_notes_a_worktree_that_is_gone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    task = queue(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    assert task.worktree_path is not None
    task.worktree_path.rename(tmp_path / "moved-away")
    TaskRunner(settings).recover()
    interrupted = last_status_change(conn, task.id)["interrupted"]
    assert interrupted == {
        "reason": RESTART_REASON,
        "commits": None,
        "uncommitted": None,
        "stopped_process": None,
    }


def test_recover_leaves_waiting_and_finished_tasks_alone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queue(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    tasks.transition(conn, task.id, Status.WAITING_FOR_USER)
    assert TaskRunner(settings).recover() == []
