"""Tasks: RepoCop's record of a template sync, in the RepoCop-owned worktree it commits in.

A task records its repository, workflow, branch, worktree, base commit and status. It is queued,
then running while its work is done, then completed or failed. Status changes, and what the work
reported, are appended to `task_events`. A task that a stopped RepoCop left queued or running
fails, as `app_restarted`, so it can be run again.

The repository's workflows are the skills committed in it, which the developer runs in their
own agent, and a workflow's line is what they type there to run it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, repositories, worktrees
from repocop.services.repositories import Repository
from repocop.services.worktrees import Changes

RESTARTED = "app_restarted"
SKILLS_FOLDER = ".claude/skills"
SKILL_FILE = "SKILL.md"
WORKFLOW_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


class TaskError(RepoCopError):
    """A task can't be changed as asked."""


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# The status machine (specs/architecture.md): the moves allowed out of each status.
_ALLOWED: dict[Status, frozenset[Status]] = {
    Status.QUEUED: frozenset({Status.RUNNING, Status.FAILED}),
    Status.RUNNING: frozenset({Status.COMPLETED, Status.FAILED}),
}


@dataclass(frozen=True)
class Task:
    id: int
    repository_id: int
    workflow: str
    branch: str | None
    worktree_path: Path | None
    base_commit: str | None
    status: Status
    error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Task:
        return cls(
            id=row["id"],
            repository_id=row["repository_id"],
            workflow=row["workflow"],
            branch=row["branch"],
            worktree_path=Path(row["worktree_path"]) if row["worktree_path"] else None,
            base_commit=row["base_commit"],
            status=Status(row["status"]),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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


def workflow_line(workflow: str, requirement_path: str) -> str:
    """The line that runs `workflow` on the requirement at `requirement_path` in an agent
    session: `/implement specs/changes/todo/bulk-import.md`. The repository's skill does the
    rest."""
    return f"/{workflow} {requirement_path}"


def create(conn: sqlite3.Connection, repository_id: int, workflow: str) -> Task:
    """Queue a task; its worktree comes later."""
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


def transition(
    conn: sqlite3.Connection, task_id: int, to: Status, *, error: str | None = None
) -> Task:
    """Move a task to `to` if the status machine allows it, recording a status_change event."""
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
        _append_event(conn, task_id, "status_change", payload, now)
    return Task.from_row(updated)


def fail_unfinished(conn: sqlite3.Connection) -> list[Task]:
    """Fail every task still queued or running, as RESTARTED, oldest first.

    Only right while no task's work is under way, as when RepoCop starts: then a task still
    queued or running is one a stopped RepoCop cut off.
    """
    rows = conn.execute(
        "SELECT id FROM tasks WHERE status IN (?, ?) ORDER BY id",
        (Status.QUEUED.value, Status.RUNNING.value),
    ).fetchall()
    return [transition(conn, row["id"], Status.FAILED, error=RESTARTED) for row in rows]


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


def get(conn: sqlite3.Connection, task_id: int) -> Task | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return Task.from_row(row) if row else None


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


def _append_event(
    conn: sqlite3.Connection, task_id: int, kind: str, payload: dict[str, Any], now: str
) -> None:
    conn.execute(
        "INSERT INTO task_events (task_id, seq, kind, payload_json, created_at)"
        " SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ? FROM task_events WHERE task_id = ?",
        (task_id, kind, json.dumps(payload), now, task_id),
    )
