"""Tasks: one workflow run on a requirement, in the requirement's RepoCop-owned worktree.

A task records its repository, requirement, workflow (a skill committed in the repository),
branch, worktree, base commit and status (ADR-009). At most one task per worktree is active
(queued, running or waiting_for_user) at a time, which the database enforces (invariant 5). The
first task on a requirement creates its worktree; later ones reuse the same worktree, branch and
base commit (ADR-012). Status changes are appended to `task_events`.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import claude, git, repositories, requirements, worktrees
from repocop.services.repositories import Repository
from repocop.services.requirements import Location, Requirement
from repocop.services.worktrees import Changes

RESTARTED = "app_restarted"
SKILLS_FOLDER = ".claude/skills"
SKILL_FILE = "SKILL.md"
WORKFLOW_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")

# One lock per requirement, by repository and path. A requirement's starts run one at a time, so
# the active-task check and the insert can't interleave, and none runs while its starts are held.
_START_LOCKS: defaultdict[tuple[int, str], threading.Lock] = defaultdict(threading.Lock)
_START_LOCKS_GUARD = threading.Lock()


class TaskError(RepoCopError):
    """A task can't be started or changed as asked."""


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE = frozenset({Status.QUEUED, Status.RUNNING, Status.WAITING_FOR_USER})

# The status machine (specs/architecture.md): the moves allowed out of each status.
_ALLOWED: dict[Status, frozenset[Status]] = {
    Status.QUEUED: frozenset({Status.RUNNING, Status.CANCELLED, Status.FAILED}),
    Status.RUNNING: frozenset(
        {Status.WAITING_FOR_USER, Status.COMPLETED, Status.FAILED, Status.CANCELLED}
    ),
    Status.WAITING_FOR_USER: frozenset({Status.RUNNING, Status.COMPLETED, Status.CANCELLED}),
}


@dataclass(frozen=True)
class Task:
    id: int
    repository_id: int
    requirement_id: int | None
    workflow: str
    branch: str | None
    worktree_path: Path | None
    base_commit: str | None
    status: Status
    claude_session_id: str | None
    error: str | None
    created_at: str
    updated_at: str
    session_pid: int | None = None  # the live Claude Code process, while a session runs
    session_pid_start: str | None = None  # its start time, so a reused id isn't mistaken for it

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Task:
        return cls(
            id=row["id"],
            repository_id=row["repository_id"],
            requirement_id=row["requirement_id"],
            workflow=row["workflow"],
            branch=row["branch"],
            worktree_path=Path(row["worktree_path"]) if row["worktree_path"] else None,
            base_commit=row["base_commit"],
            status=Status(row["status"]),
            claude_session_id=row["claude_session_id"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            session_pid=row["session_pid"],
            session_pid_start=row["session_pid_start"],
        )


@dataclass(frozen=True)
class TaskEvent:
    seq: int
    kind: str
    payload: dict[str, Any]
    created_at: str


def workflows(settings: Settings, repository: Repository) -> list[str]:
    """Skills committed at HEAD as `.claude/skills/<name>/SKILL.md` in the primary checkout."""
    checkout = repositories.require_checkout(repository, settings)
    names = []
    for path in git.files_at(checkout, "HEAD", SKILLS_FOLDER):
        parts = PurePosixPath(path).parts
        if len(parts) == 4 and parts[3] == SKILL_FILE and WORKFLOW_NAME.fullmatch(parts[2]):
            names.append(parts[2])
    return sorted(names)


def start(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, workflow: str
) -> Task:
    """Queue `workflow` on the requirement, in its worktree (created on the first start).

    Refused unless the requirement is at its path with no uncommitted changes, has no other
    active task, and `workflow` is a skill committed in the repository. The first task records a
    requirement the database doesn't have yet.
    """
    repository = _repository_of(conn, requirement)
    if workflow not in workflows(settings, repository):
        raise TaskError(
            f"{workflow!r} isn't a skill committed in {SKILLS_FOLDER} of {repository.name}"
        )
    with hold_starts(requirement):
        where = requirements.location(settings, repository, requirement)
        if where is not Location.ACTIVE:
            raise TaskError(f"{requirement.name} is {where}, so no new tasks start on it")
        if requirements.is_uncommitted(settings, repository, requirement):
            raise TaskError(
                f"{requirement.name} has uncommitted changes. Commit it first, so the task "
                "works from the text you see."
            )
        _refuse_while_active(conn, requirement)
        worktree = _worktree_for(conn, settings, repository, requirement)
        return _queue(conn, repository, requirement, workflow, worktree)


def start_on_branch(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, workflow: str
) -> Task:
    """Queue `workflow` on the requirement's branch, in the worktree its earlier tasks share.

    For a workflow of RepoCop's own, which no skill backs. Refused before the
    requirement's first task, when it has no branch yet, and while another of its tasks is active.
    """
    repository = _repository_of(conn, requirement)
    with hold_starts(requirement):
        _refuse_while_active(conn, requirement)
        if last_with_worktree(conn, requirement) is None:
            raise TaskError(f"{requirement.name} has no branch yet: its first task creates one")
        worktree = _worktree_for(conn, settings, repository, requirement)
        return _queue(conn, repository, requirement, workflow, worktree)


@contextlib.contextmanager
def hold_starts(requirement: Requirement) -> Iterator[None]:
    """Keep tasks from starting on the requirement for the length of the block.

    A start asked for meanwhile waits for the block to end, as a second block does. So a
    requirement with no active task when the block begins has none until it ends.
    """
    with _START_LOCKS_GUARD:
        lock = _START_LOCKS[requirement.repository_id, requirement.path]
    with lock:
        yield


def transition(
    conn: sqlite3.Connection,
    task_id: int,
    to: Status,
    *,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> Task:
    """Move a task to `to` if the status machine allows it, recording a status_change event.

    `details` are added to the event, e.g. where an interrupted task left its worktree.
    """
    now = db.timestamp()
    with db.transaction(conn):
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskError(f"task #{task_id} doesn't exist")
        current = Status(row["status"])
        if to not in _ALLOWED.get(current, frozenset()):
            raise TaskError(f"task #{task_id} can't go from {current} to {to}")
        updated = conn.execute(
            "UPDATE tasks SET status = ?, error = COALESCE(?, error), updated_at = ?"
            " WHERE id = ? RETURNING *",
            (to.value, error, now, task_id),
        ).fetchone()
        payload: dict[str, Any] = {"status": to.value}
        if error:
            payload["error"] = error
        payload |= details or {}
        _append_event(conn, task_id, "status_change", payload, now)
    return Task.from_row(updated)


def start_again(conn: sqlite3.Connection, settings: Settings, task: Task) -> Task:
    """Queue the same workflow on the same requirement, after a task failed or was cancelled.

    It runs in the requirement's worktree as that task left it, with a new session. A workflow
    whose name no skill can have is RepoCop's own, and starts on the branch again.
    """
    if task.status not in (Status.FAILED, Status.CANCELLED):
        raise TaskError(
            f"task #{task.id} is {task.status}; only a failed or cancelled task can start again"
        )
    requirement = requirements.get(conn, task.requirement_id) if task.requirement_id else None
    if requirement is None:
        raise TaskError(f"task #{task.id} has no requirement to start again on")
    if WORKFLOW_NAME.fullmatch(task.workflow):
        return start(conn, settings, requirement, task.workflow)
    return start_on_branch(conn, settings, requirement, task.workflow)


def create(conn: sqlite3.Connection, repository_id: int, workflow: str) -> Task:
    """Queue a task with no requirement (e.g. a template sync); its worktree comes later."""
    now = db.timestamp()
    with db.transaction(conn):
        row = conn.execute(
            "INSERT INTO tasks (repository_id, workflow, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?) RETURNING *",
            (repository_id, workflow, Status.QUEUED.value, now, now),
        ).fetchone()
        _append_event(conn, row["id"], "status_change", {"status": Status.QUEUED}, now)
    return Task.from_row(row)


def set_worktree(
    conn: sqlite3.Connection, task_id: int, branch: str, path: Path, base_commit: str
) -> Task:
    """Record the branch, worktree and base commit a task works in."""
    with db.transaction(conn):
        row = conn.execute(
            "UPDATE tasks SET branch = ?, worktree_path = ?, base_commit = ?, updated_at = ?"
            " WHERE id = ? RETURNING *",
            (branch, str(path), base_commit, db.timestamp(), task_id),
        ).fetchone()
    return Task.from_row(row)


def cancel(conn: sqlite3.Connection, task: Task) -> Task:
    """Cancel a task with no live session: one that is queued or waiting for the user."""
    if task.status not in (Status.QUEUED, Status.WAITING_FOR_USER):
        raise TaskError(f"task #{task.id} is {task.status}, so it can't be cancelled here")
    return transition(conn, task.id, Status.CANCELLED)


def mark_done(conn: sqlite3.Connection, task: Task) -> Task:
    """The user's call that a task waiting for them is finished (ADR-009)."""
    if task.status is not Status.WAITING_FOR_USER:
        raise TaskError(
            f"task #{task.id} is {task.status}; only a task waiting for you can be marked done"
        )
    return transition(conn, task.id, Status.COMPLETED)


def record(conn: sqlite3.Connection, task_id: int, kind: str, payload: dict[str, Any]) -> None:
    """Append one event to the task's log."""
    with db.transaction(conn):
        _append_event(conn, task_id, kind, payload, db.timestamp())


def events_after(conn: sqlite3.Connection, task_id: int, seq: int) -> list[TaskEvent]:
    """The task's events with a sequence number above `seq`, in order."""
    rows = conn.execute(
        "SELECT seq, kind, payload_json, created_at FROM task_events"
        " WHERE task_id = ? AND seq > ? ORDER BY seq",
        (task_id, seq),
    )
    return [
        TaskEvent(row["seq"], row["kind"], json.loads(row["payload_json"]), row["created_at"])
        for row in rows
    ]


def worktree_changes(conn: sqlite3.Connection, settings: Settings, task: Task) -> Changes | None:
    """Git status and the diff of everything the task's worktree changed; None if it's gone."""
    repository = repositories.get(conn, task.repository_id)
    if repository is None or task.worktree_path is None or task.base_commit is None:
        return None
    return worktrees.changes(repository, settings, task.worktree_path, task.base_commit)


def worktree(conn: sqlite3.Connection, settings: Settings, task: Task) -> Path | None:
    """The task's worktree, while it's still one of its repository's worktrees on disk."""
    repository = repositories.get(conn, task.repository_id)
    if repository is None or task.worktree_path is None:
        return None
    present = worktrees.is_worktree(repository, settings, task.worktree_path)
    return task.worktree_path if present else None


def interruption(conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
    """Where the task stopped, if its current status came from a RepoCop restart."""
    row = conn.execute(
        "SELECT payload_json FROM task_events WHERE task_id = ? AND kind = 'status_change'"
        " ORDER BY seq DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    interrupted = json.loads(row["payload_json"]).get("interrupted") if row else None
    return interrupted if isinstance(interrupted, dict) else None


def set_process(conn: sqlite3.Connection, task_id: int, pid: int | None, start: str | None) -> None:
    """Record the task's live Claude Code process, or clear it once the session has ended."""
    with db.transaction(conn):
        conn.execute(
            "UPDATE tasks SET session_pid = ?, session_pid_start = ? WHERE id = ?",
            (pid, start, task_id),
        )


def set_session(conn: sqlite3.Connection, task_id: int, session_id: str) -> None:
    """Remember the task's Claude session id, the key for resuming it (ADR-010). First one wins."""
    with db.transaction(conn):
        conn.execute(
            "UPDATE tasks SET claude_session_id = ? WHERE id = ? AND claude_session_id IS NULL",
            (session_id, task_id),
        )


def resume_command(conn: sqlite3.Connection, settings: Settings, task: Task) -> str | None:
    """The terminal command that continues the task's Claude session, once it's safe to.

    None while any task is active in the task's worktree: RepoCop may still resume or run
    a session there, and two writers in one session interleave. None too for a task that never
    got a session, or whose worktree is no longer one of its repository's worktrees.
    """
    if not task.claude_session_id or task.worktree_path is None:
        return None
    busy = conn.execute(
        "SELECT 1 FROM tasks WHERE worktree_path = ? AND status IN (?, ?, ?)",
        (str(task.worktree_path), *sorted(ACTIVE)),
    ).fetchone()
    repository = repositories.get(conn, task.repository_id)
    if busy or repository is None:
        return None
    if not worktrees.is_worktree(repository, settings, task.worktree_path):
        return None
    return claude.resume_command(settings, task.worktree_path, task.claude_session_id)


def get(conn: sqlite3.Connection, task_id: int) -> Task | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return Task.from_row(row) if row else None


def list_for_requirement(conn: sqlite3.Connection, requirement: Requirement) -> list[Task]:
    if requirement.id is None:
        return []
    rows = conn.execute(
        "SELECT * FROM tasks WHERE requirement_id = ? ORDER BY id DESC", (requirement.id,)
    )
    return [Task.from_row(row) for row in rows]


def list_for_repository(
    conn: sqlite3.Connection, repository: Repository, workflow: str | None = None
) -> list[Task]:
    """The repository's tasks, newest first, optionally only those running one workflow."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE repository_id = ? AND (? IS NULL OR workflow = ?)"
        " ORDER BY id DESC",
        (repository.id, workflow, workflow),
    )
    return [Task.from_row(row) for row in rows]


def list_active(conn: sqlite3.Connection) -> list[Task]:
    """Every active task, in any repository, newest first."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status IN (SELECT value FROM json_each(?)) ORDER BY id DESC",
        (json.dumps(sorted(ACTIVE)),),
    )
    return [Task.from_row(row) for row in rows]


def search(conn: sqlite3.Connection, text: str, limit: int) -> list[Task]:
    """Up to `limit` tasks, newest first, whose id is `text` (with or without its `#`), or whose
    branch or workflow holds it, whatever its case."""
    term = text.strip()
    pattern = "%" + re.sub(r"([\\%_])", r"\\\1", term) + "%"
    rows = conn.execute(
        "SELECT * FROM tasks WHERE CAST(id AS TEXT) = ?"
        " OR branch LIKE ? ESCAPE '\\' OR workflow LIKE ? ESCAPE '\\'"
        " ORDER BY id DESC LIMIT ?",
        (term.removeprefix("#"), pattern, pattern, limit),
    )
    return [Task.from_row(row) for row in rows]


def active_task(conn: sqlite3.Connection, requirement: Requirement) -> Task | None:
    """The requirement's active task. Only its latest task can be one: starts wait for it."""
    if requirement.id is None:
        return None
    row = conn.execute(
        "SELECT * FROM tasks WHERE requirement_id = ? ORDER BY id DESC LIMIT 1", (requirement.id,)
    ).fetchone()
    latest = Task.from_row(row) if row else None
    return latest if latest is not None and latest.status in ACTIVE else None


def last_with_worktree(conn: sqlite3.Connection, requirement: Requirement) -> Task | None:
    """The requirement's newest task that has a worktree, or None before its first task.

    Its branch, worktree and base commit are the requirement's: all its tasks share them.
    """
    if requirement.id is None:
        return None
    row = conn.execute(
        "SELECT * FROM tasks WHERE requirement_id = ? AND worktree_path IS NOT NULL"
        " ORDER BY id DESC LIMIT 1",
        (requirement.id,),
    ).fetchone()
    return Task.from_row(row) if row else None


def _worktree_for(
    conn: sqlite3.Connection, settings: Settings, repository: Repository, requirement: Requirement
) -> tuple[str, Path, str]:
    """(branch, path, base commit): the requirement's existing worktree, or a new one."""
    previous = last_with_worktree(conn, requirement)
    if previous is not None:
        path, branch, base = previous.worktree_path, previous.branch, previous.base_commit
        if path is None or not branch or not base:
            raise TaskError(f"task #{previous.id} has an incomplete worktree record")
        if not worktrees.is_worktree(repository, settings, path):
            raise TaskError(
                f"the worktree {path} for {requirement.name} is gone; RepoCop doesn't "
                "recreate worktrees on its own"
            )
        return branch, path, base
    name, branch = worktrees.requirement_names(requirement.name)
    worktree = worktrees.create(repository, settings, name, branch)
    return worktree.branch, worktree.path, worktree.base_commit


def _refuse_while_active(conn: sqlite3.Connection, requirement: Requirement) -> None:
    if active := active_task(conn, requirement):
        raise TaskError(
            f"task #{active.id} ({active.workflow}) is still {active.status} on "
            f"{requirement.name}. Finish or cancel it first."
        )


def _queue(
    conn: sqlite3.Connection,
    repository: Repository,
    requirement: Requirement,
    workflow: str,
    worktree: tuple[str, Path, str],
) -> Task:
    """A new queued task for `workflow` in `worktree`: its (branch, path, base commit)."""
    branch, path, base = worktree
    requirement = requirements.record(conn, requirement)
    now = db.timestamp()
    try:
        with db.transaction(conn):
            row = conn.execute(
                "INSERT INTO tasks (repository_id, requirement_id, workflow, branch,"
                " worktree_path, base_commit, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
                (
                    repository.id,
                    requirement.id,
                    workflow,
                    branch,
                    str(path),
                    base,
                    Status.QUEUED.value,
                    now,
                    now,
                ),
            ).fetchone()
            _append_event(conn, row["id"], "status_change", {"status": Status.QUEUED}, now)
    except sqlite3.IntegrityError as exc:
        raise TaskError(f"another task is already active in {path}") from exc
    return Task.from_row(row)


def _repository_of(conn: sqlite3.Connection, requirement: Requirement) -> Repository:
    repository = repositories.get(conn, requirement.repository_id)
    if repository is None:
        raise TaskError(f"{requirement.name}'s repository is no longer registered")
    return repository


def _append_event(
    conn: sqlite3.Connection, task_id: int, kind: str, payload: dict[str, Any], now: str
) -> None:
    conn.execute(
        "INSERT INTO task_events (task_id, seq, kind, payload_json, created_at)"
        " SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ? FROM task_events WHERE task_id = ?",
        (task_id, kind, json.dumps(payload), now, task_id),
    )
