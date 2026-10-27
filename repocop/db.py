"""SQLite persistence: connections, explicit transactions, and forward-only migrations.

The database holds execution state and references only (invariant 4): repo paths, requirement
paths, task state, the event log, and pull request addresses. Requirement names and text, and
repo config, are read from the repos themselves.

Migrations are numbered by `PRAGMA user_version`. Never edit a released migration; append a
new one.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from repocop.config import FORMER_NAME
from repocop.errors import DatabaseError

logger = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000

MIGRATIONS: tuple[str, ...] = (
    # 1: initial schema (see "Data model" in specs/architecture.md)
    """
    CREATE TABLE repositories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        remote_url TEXT NOT NULL,
        primary_path TEXT NOT NULL UNIQUE,
        worktrees_root TEXT NOT NULL,
        default_branch TEXT NOT NULL,
        requirement_path_pattern TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- id is the global requirement id, assigned by RepoCop, not SQLite (ADR-013).
    CREATE TABLE requirements (
        id INTEGER PRIMARY KEY,
        repository_id INTEGER NOT NULL REFERENCES repositories (id),
        path TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'feature' CHECK (kind IN ('feature', 'fix')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (repository_id, path)
    );

    -- id is a global counter that is never reused (ADR-007). branch, worktree_path and
    -- base_commit stay NULL until the task's worktree exists.
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repository_id INTEGER NOT NULL REFERENCES repositories (id),
        requirement_id INTEGER REFERENCES requirements (id),
        workflow TEXT NOT NULL,
        branch TEXT,
        worktree_path TEXT,
        base_commit TEXT,
        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
            'queued', 'running', 'waiting_for_user', 'completed', 'failed', 'cancelled'
        )),
        claude_session_id TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX tasks_repository_id ON tasks (repository_id);
    CREATE INDEX tasks_requirement_id ON tasks (requirement_id);

    -- Append-only; seq orders each task's events.
    CREATE TABLE task_events (
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES tasks (id),
        seq INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN (
            'user_instruction', 'assistant_text', 'tool_use', 'tool_result',
            'command_output', 'status_change', 'error', 'raw'
        )),
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (task_id, seq)
    );
    """,
    # 2: at most one active task per worktree (invariant 5)
    """
    CREATE UNIQUE INDEX tasks_one_active_per_worktree ON tasks (worktree_path)
        WHERE status IN ('queued', 'running', 'waiting_for_user');
    """,
    # 3: a running task's Claude Code process (id and start time), so a restart can stop one
    # left behind
    """
    ALTER TABLE tasks ADD COLUMN session_pid INTEGER;
    ALTER TABLE tasks ADD COLUMN session_pid_start TEXT;
    """,
    # 4: the pull request a RepoCop branch last had open. Only its address: the
    # pull request itself is on GitHub.
    """
    CREATE TABLE pull_requests (
        repository_id INTEGER NOT NULL REFERENCES repositories (id),
        branch TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (repository_id, branch)
    );
    """,
    # 5: a repository's requirements are the Markdown files in a folder, named by their files
    # with no id, so the folder replaces the file-name pattern that held the id.
    """
    ALTER TABLE repositories
        ADD COLUMN requirements_dir TEXT NOT NULL DEFAULT 'specs/changes/todo';
    UPDATE repositories SET requirements_dir = CASE
        WHEN instr(requirement_path_pattern, '/') = 0 THEN '.'
        ELSE rtrim(
            rtrim(requirement_path_pattern, replace(requirement_path_pattern, '/', '')), '/'
        )
    END;
    ALTER TABLE repositories DROP COLUMN requirement_path_pattern;
    """,
    # 6: a repository's changes folder, holding its todo/ and archive/, replaces its todo folder
    # alone, whose parent it is.
    """
    ALTER TABLE repositories RENAME COLUMN requirements_dir TO changes_dir;
    UPDATE repositories SET changes_dir = CASE
        WHEN instr(changes_dir, '/') = 0 THEN '.'
        ELSE rtrim(rtrim(changes_dir, replace(changes_dir, '/', '')), '/')
    END;
    """,
    # 7: a task a restart stopped is stored with a reason that names no product, so a later
    # rename leaves stored data alone.
    f"""
    UPDATE tasks SET error = 'app_restarted' WHERE error = '{FORMER_NAME}_restarted';
    UPDATE task_events SET payload_json = json_set(payload_json, '$.error', 'app_restarted')
    WHERE kind = 'status_change'
        AND json_extract(payload_json, '$.error') = '{FORMER_NAME}_restarted';
    """,  # noqa: S608 - a constant, never input
    # 8: a requirement has no kind: nothing sets one once requirements are written outside
    # RepoCop, and every branch it names starts agent/ whatever the kind.
    """
    ALTER TABLE requirements DROP COLUMN kind;
    """,
)


def connect(path: Path) -> sqlite3.Connection:
    """Open the database, creating its directory. Transactions are explicit: see `transaction`.

    The connection may be used from any thread, by one thread at a time.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, autocommit=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseError(f"cannot open database {path}: {exc}") from exc
    return conn


def timestamp() -> str:
    """The current time in the stored format: UTC ISO-8601."""
    return datetime.now(UTC).isoformat()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block in one write transaction: commit on success, roll back on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations in one transaction. Refuse a database from a newer RepoCop.

    Needs a connection from `connect` (autocommit=True). In sqlite3's default mode,
    executescript() commits first, so a failed migration couldn't roll back.
    """
    if conn.autocommit is not True:
        raise DatabaseError("migrations need a connection with autocommit=True (see db.connect)")
    with transaction(conn):
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        latest = len(MIGRATIONS)
        if version > latest:
            raise DatabaseError(
                f"database schema version {version} is newer than this version of RepoCop supports "
                f"({latest}); upgrade RepoCop"
            )
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {number}")
    if version < latest:
        logger.info("Migrated database from schema version %d to %d", version, latest)
