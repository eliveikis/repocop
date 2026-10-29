"""Tasks: the record of a template sync's run, its status machine and events, and the
repository's workflows."""

import sqlite3
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import repositories, tasks, worktrees
from repocop.services.repositories import Repository
from repocop.services.tasks import Status, Task, TaskError
from tests.conftest import run_git

SYNC = "template-sync"


def commit_skills(checkout: Path, *names: str) -> None:
    for name in names:
        folder = checkout / ".claude" / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=checkout)
    run_git("commit", "-qm", "Add skills", cwd=checkout)


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo), default_branch="main").repository


def in_a_worktree(conn: sqlite3.Connection, settings: Settings, repo: Repository) -> Task:
    """A queued task with a worktree of its own, as a sync makes one."""
    task = tasks.create(conn, repo.id, SYNC)
    name, branch = worktrees.task_names(SYNC, task.id)
    made = worktrees.create(repo, settings, name, branch)
    return tasks.set_worktree(conn, task.id, made.branch, made.path, made.base_commit)


# ---------------------------------------------------------------- workflows


def test_workflows_are_the_skills_committed_at_head(settings: Settings, repo: Repository) -> None:
    commit_skills(repo.primary_path, "implement", "review-requirement")
    uncommitted = repo.primary_path / ".claude" / "skills" / "draft"
    uncommitted.mkdir()
    (uncommitted / "SKILL.md").write_text("# draft\n")
    assert tasks.workflows(settings, repo) == ["implement", "review-requirement"]


def test_workflows_skip_folders_without_a_usable_name(settings: Settings, repo: Repository) -> None:
    commit_skills(repo.primary_path, "implement", "Bad_Name")
    assert tasks.workflows(settings, repo) == ["implement"]


# ---------------------------------------------------------------- records


def test_create_queues_a_task_with_no_worktree_yet(
    conn: sqlite3.Connection, repo: Repository
) -> None:
    task = tasks.create(conn, repo.id, SYNC)
    assert (task.workflow, task.status, task.worktree_path) == (SYNC, Status.QUEUED, None)
    [event] = tasks.events_after(conn, task.id, 0)
    assert (event.kind, event.payload) == ("status_change", {"status": "queued"})


def test_set_worktree_records_where_a_task_works(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = tasks.create(conn, repo.id, SYNC)
    path = settings.worktrees_root / "sample" / f"template-sync-{task.id}"
    updated = tasks.set_worktree(conn, task.id, "agent/template-sync-1", path, "abc123")
    assert (updated.branch, updated.worktree_path, updated.base_commit) == (
        "agent/template-sync-1",
        path,
        "abc123",
    )


def test_list_for_repository_filters_by_workflow_newest_first(
    conn: sqlite3.Connection, repo: Repository
) -> None:
    first = tasks.create(conn, repo.id, SYNC)
    other = tasks.create(conn, repo.id, "other")
    second = tasks.create(conn, repo.id, SYNC)
    listed = tasks.list_for_repository(conn, repo, workflow=SYNC)
    assert [task.id for task in listed] == [second.id, first.id]
    assert [task.id for task in tasks.list_for_repository(conn, repo)][1] == other.id


def test_get_returns_none_for_an_unknown_id(conn: sqlite3.Connection) -> None:
    assert tasks.get(conn, 999) is None


# ---------------------------------------------------------------- status machine and events


@pytest.mark.parametrize("path", [["running", "completed"], ["running", "failed"], ["failed"]])
def test_transition_follows_the_status_machine(
    conn: sqlite3.Connection, repo: Repository, path: list[str]
) -> None:
    task = tasks.create(conn, repo.id, SYNC)
    for status in path:
        task = tasks.transition(conn, task.id, Status(status))
    assert task.status is Status(path[-1])


@pytest.mark.parametrize(
    ("path", "illegal"),
    [
        ([], "completed"),
        (["running", "completed"], "failed"),
        (["running", "failed"], "running"),
    ],
)
def test_transition_refuses_moves_the_machine_does_not_allow(
    conn: sqlite3.Connection, repo: Repository, path: list[str], illegal: str
) -> None:
    task = tasks.create(conn, repo.id, SYNC)
    for status in path:
        task = tasks.transition(conn, task.id, Status(status))
    with pytest.raises(TaskError, match="can't go"):
        tasks.transition(conn, task.id, Status(illegal))


def test_transition_to_failed_records_the_error(conn: sqlite3.Connection, repo: Repository) -> None:
    task = tasks.create(conn, repo.id, SYNC)
    failed = tasks.transition(conn, task.id, Status.FAILED, error="boom")
    assert failed.error == "boom"
    last = tasks.events_after(conn, task.id, 0)[-1]
    assert (last.kind, last.payload) == ("status_change", {"status": "failed", "error": "boom"})


def test_record_appends_events_in_order(conn: sqlite3.Connection, repo: Repository) -> None:
    task = tasks.create(conn, repo.id, SYNC)
    tasks.record(conn, task.id, "raw", {"text": "Committed 2 files"})
    tasks.record(conn, task.id, "error", {"error": "boom"})
    events = tasks.events_after(conn, task.id, 1)
    assert [(e.seq, e.kind) for e in events] == [(2, "raw"), (3, "error")]


def test_fail_unfinished_fails_queued_and_running_tasks_and_leaves_ended_ones(
    conn: sqlite3.Connection, repo: Repository
) -> None:
    queued, running = tasks.create(conn, repo.id, SYNC), tasks.create(conn, repo.id, SYNC)
    tasks.transition(conn, running.id, Status.RUNNING)
    done = tasks.create(conn, repo.id, SYNC)
    tasks.transition(conn, done.id, Status.RUNNING)
    tasks.transition(conn, done.id, Status.COMPLETED)
    failed = tasks.fail_unfinished(conn)
    assert [(task.id, task.status, task.error) for task in failed] == [
        (queued.id, Status.FAILED, tasks.RESTARTED),
        (running.id, Status.FAILED, tasks.RESTARTED),
    ]
    assert (tasks.get(conn, done.id) or done).status is Status.COMPLETED


# ---------------------------------------------------------------- the worktree


def test_worktree_changes_shows_what_the_task_changed(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = in_a_worktree(conn, settings, repo)
    assert task.worktree_path is not None
    (task.worktree_path / "notes.txt").write_text("a new note\n")
    changes = tasks.worktree_changes(conn, settings, task)
    assert changes is not None and "+a new note" in changes.diff


def test_worktree_changes_is_none_once_the_worktree_is_gone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    task = in_a_worktree(conn, settings, repo)
    assert task.worktree_path is not None
    task.worktree_path.rename(tmp_path / "moved-away")
    assert tasks.worktree_changes(conn, settings, task) is None
    assert tasks.worktree(conn, settings, task) is None
