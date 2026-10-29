"""Persistence: connections, explicit transactions, forward-only migrations, and the schema."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop import db
from repocop.config import FORMER_NAME, Settings
from repocop.errors import DatabaseError
from repocop.main import create_app

NOW = "2026-09-25T12:00:00+00:00"
TASK_STATUSES = ("queued", "running", "completed", "failed")
EVENT_KINDS = ("status_change", "error", "raw")


def user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    return {row[0] for row in rows} - {"sqlite_sequence"}


def columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def add_repository(connection: sqlite3.Connection, name: str = "sample") -> int:
    cursor = connection.execute(
        "INSERT INTO repositories (name, remote_url, primary_path, worktrees_root,"
        " default_branch, changes_dir, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            f"https://example.invalid/{name}.git",
            f"/code/{name}",
            f"/agent-worktrees/{name}",
            "main",
            "specs/changes",
            NOW,
            NOW,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_task(connection: sqlite3.Connection, repository_id: int, status: str = "queued") -> int:
    cursor = connection.execute(
        "INSERT INTO tasks (repository_id, workflow, status, created_at, updated_at)"
        " VALUES (?, 'template-sync', ?, ?, ?)",
        (repository_id, status, NOW, NOW),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_event(connection: sqlite3.Connection, task_id: int, seq: int, kind: str = "raw") -> None:
    connection.execute(
        "INSERT INTO task_events (task_id, seq, kind, payload_json, created_at)"
        " VALUES (?, ?, ?, '{}', ?)",
        (task_id, seq, kind, NOW),
    )


# ---------------------------------------------------------------- connections


def test_connect_creates_missing_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "repocop.db"
    db.connect(path).close()
    assert path.is_file()


def test_connect_enables_foreign_keys_wal_and_busy_timeout(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_connect_returns_a_connection_usable_from_any_thread(conn: sqlite3.Connection) -> None:
    results: list[int] = []
    thread = threading.Thread(target=lambda: results.append(conn.execute("SELECT 1").fetchone()[0]))
    thread.start()
    thread.join()
    assert results == [1]


def test_timestamp_is_utc_iso_8601() -> None:
    assert datetime.fromisoformat(db.timestamp()).utcoffset() == timedelta(0)


def test_connect_reports_unopenable_path(tmp_path: Path) -> None:
    directory = tmp_path / "is-a-directory"
    directory.mkdir()
    with pytest.raises(DatabaseError, match="is-a-directory"):
        db.connect(directory)


# ---------------------------------------------------------------- transactions


def test_transaction_commits_on_success(conn: sqlite3.Connection) -> None:
    with db.transaction(conn):
        add_repository(conn)
    assert conn.execute("SELECT count(*) FROM repositories").fetchone()[0] == 1


def test_transaction_rolls_back_on_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), db.transaction(conn):
        add_repository(conn)
        raise RuntimeError("boom")
    assert conn.execute("SELECT count(*) FROM repositories").fetchone()[0] == 0
    assert not conn.in_transaction


# ---------------------------------------------------------------- migrations


def test_migrate_creates_schema_at_latest_version(conn: sqlite3.Connection) -> None:
    expected = {"repositories", "tasks", "task_events", "pull_requests"}
    assert table_names(conn) == expected
    assert user_version(conn) == len(db.MIGRATIONS)


def test_migrate_is_idempotent(conn: sqlite3.Connection) -> None:
    add_repository(conn)
    db.migrate(conn)
    assert user_version(conn) == len(db.MIGRATIONS)
    assert conn.execute("SELECT count(*) FROM repositories").fetchone()[0] == 1


def test_migrate_applies_only_pending_migrations(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_repository(conn)
    extra = "ALTER TABLE repositories ADD COLUMN note TEXT;"
    monkeypatch.setattr(db, "MIGRATIONS", (*db.MIGRATIONS, extra))
    db.migrate(conn)
    assert user_version(conn) == len(db.MIGRATIONS)
    assert "note" in columns(conn, "repositories")
    assert conn.execute("SELECT count(*) FROM repositories").fetchone()[0] == 1


def test_migrate_rolls_back_a_failing_migration(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = user_version(conn)
    broken = "CREATE TABLE half_done (id INTEGER); INSERT INTO no_such_table VALUES (1);"
    monkeypatch.setattr(db, "MIGRATIONS", (*db.MIGRATIONS, broken))
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)
    assert user_version(conn) == version
    assert "half_done" not in table_names(conn)
    assert not conn.in_transaction


@pytest.mark.parametrize(
    ("pattern", "folder"),
    [
        ("specs/changes/todo/req-{id}-{slug}.md", "specs/changes"),
        ("docs/rfcs/{slug}-{id}.md", "docs"),
        ("req-{id}-{slug}.md", "."),
    ],
)
def test_migrate_keeps_each_repositorys_changes_folder_from_its_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pattern: str, folder: str
) -> None:
    fresh = db.connect(tmp_path / "before.db")
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:4])
        db.migrate(fresh)
    fresh.execute(
        "INSERT INTO repositories (name, remote_url, primary_path, worktrees_root,"
        " default_branch, requirement_path_pattern, created_at, updated_at)"
        " VALUES ('sample', 'https://example.invalid/s.git', '/code/sample',"
        " '/agent-worktrees/sample', 'main', ?, ?, ?)",
        (pattern, NOW, NOW),
    )
    db.migrate(fresh)
    assert fresh.execute("SELECT changes_dir FROM repositories").fetchone()[0] == folder
    assert {"requirement_path_pattern", "requirements_dir"}.isdisjoint(
        columns(fresh, "repositories")
    )


def test_migrate_keeps_the_changes_folder_of_a_requirements_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = db.connect(tmp_path / "before.db")
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:5])
        db.migrate(fresh)
    fresh.execute(
        "INSERT INTO repositories (name, remote_url, primary_path, worktrees_root,"
        " default_branch, requirements_dir, created_at, updated_at)"
        " VALUES ('sample', 'https://example.invalid/s.git', '/code/sample',"
        " '/agent-worktrees/sample', 'main', 'specs/changes/todo', ?, ?)",
        (NOW, NOW),
    )
    db.migrate(fresh)
    assert fresh.execute("SELECT changes_dir FROM repositories").fetchone()[0] == "specs/changes"


def test_migrate_gives_tasks_a_restart_stopped_the_reason_that_names_no_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    former = f"{FORMER_NAME}_restarted"
    before = db.connect(tmp_path / "before.db")
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:6])
        db.migrate(before)
    repository = add_repository(before)
    stopped, failed = add_task(before, repository, status="failed"), add_task(before, repository)
    before.execute("UPDATE tasks SET error = ? WHERE id = ?", (former, stopped))
    before.execute("UPDATE tasks SET error = 'git failed' WHERE id = ?", (failed,))
    before.execute(
        "INSERT INTO task_events (task_id, seq, kind, payload_json, created_at)"
        " VALUES (?, 1, 'status_change', ?, ?)",
        (stopped, json.dumps({"to": "failed", "error": former}), NOW),
    )
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:7])
        db.migrate(before)
    errors = dict(before.execute("SELECT id, error FROM tasks").fetchall())
    assert errors == {stopped: "app_restarted", failed: "git failed"}
    payload = before.execute("SELECT payload_json FROM task_events").fetchone()[0]
    assert json.loads(payload) == {"to": "failed", "error": "app_restarted"}


def test_migrate_drops_the_requirements_kind_and_keeps_their_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = db.connect(tmp_path / "before.db")
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:7])
        db.migrate(before)
    repository = add_repository(before)
    before.execute(
        "INSERT INTO requirements (id, repository_id, path, kind, created_at, updated_at)"
        " VALUES (7, ?, 'specs/changes/todo/login-crash.md', 'fix', ?, ?)",
        (repository, NOW, NOW),
    )
    task = before.execute(
        "INSERT INTO tasks (repository_id, requirement_id, workflow, status, created_at,"
        " updated_at) VALUES (?, 7, 'implement', 'queued', ?, ?) RETURNING id",
        (repository, NOW, NOW),
    ).fetchone()[0]
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:8])
        db.migrate(before)
    assert "kind" not in columns(before, "requirements")
    row = before.execute("SELECT id, path FROM requirements").fetchone()
    assert tuple(row) == (7, "specs/changes/todo/login-crash.md")
    linked = before.execute("SELECT requirement_id FROM tasks WHERE id = ?", (task,)).fetchone()
    assert linked[0] == 7


def test_migrate_clears_what_only_agent_runs_used_and_keeps_template_syncs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = db.connect(tmp_path / "before.db")
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:8])
        db.migrate(before)
    repository = add_repository(before)
    before.execute(
        "INSERT INTO requirements (id, repository_id, path, created_at, updated_at)"
        " VALUES (1, ?, 'specs/changes/todo/bulk-import.md', ?, ?)",
        (repository, NOW, NOW),
    )

    def task(workflow: str, branch: str, status: str, requirement: int | None = None) -> int:
        cursor = before.execute(
            "INSERT INTO tasks (repository_id, requirement_id, workflow, branch, status,"
            " claude_session_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (repository, requirement, workflow, branch, status, "session", NOW, NOW),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    sync = task("template-sync", "agent/template-sync-1", "completed")
    run = task("implement", "agent/bulk-import", "waiting_for_user", requirement=1)
    review = task("Codex review", "agent/bulk-import", "completed", requirement=1)
    for each in (sync, run, review):
        add_event(before, each, 1)
    for branch in ("agent/template-sync-1", "agent/bulk-import"):
        before.execute(
            "INSERT INTO pull_requests (repository_id, branch, url, created_at)"
            " VALUES (?, ?, 'https://github.com/o/r/pull/1', ?)",
            (repository, branch, NOW),
        )
    db.migrate(before)
    assert "requirements" not in table_names(before)
    assert not {"requirement_id", "claude_session_id", "session_pid", "session_pid_start"} & (
        columns(before, "tasks")
    )
    assert [row[0] for row in before.execute("SELECT id FROM tasks")] == [sync]
    assert [row[0] for row in before.execute("SELECT task_id FROM task_events")] == [sync]
    pulls = [row[0] for row in before.execute("SELECT branch FROM pull_requests")]
    assert pulls == ["agent/template-sync-1"]
    assert before.execute("PRAGMA foreign_key_check").fetchall() == []
    cursor = before.execute(
        "INSERT INTO tasks (repository_id, workflow, status, created_at, updated_at)"
        " VALUES (?, 'template-sync', 'queued', ?, ?)",
        (repository, NOW, NOW),
    )
    assert cursor.lastrowid == review + 1  # the counter never reuses an id (ADR-007)


def test_migrate_refuses_database_from_newer_repocop(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
    with pytest.raises(DatabaseError, match="newer"):
        db.migrate(conn)


def test_migrate_refuses_a_connection_with_implicit_transactions(tmp_path: Path) -> None:
    # In sqlite3's default mode, executescript() commits first, so a migration couldn't roll back.
    legacy = sqlite3.connect(tmp_path / "legacy.db")
    try:
        with pytest.raises(DatabaseError, match="autocommit"):
            db.migrate(legacy)
        assert table_names(legacy) == set()
    finally:
        legacy.close()


# ---------------------------------------------------------------- schema


def test_schema_state_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "repocop.db"
    first = db.connect(path)
    db.migrate(first)
    task_id = add_task(first, add_repository(first), status="running")
    first.close()

    second = db.connect(path)
    db.migrate(second)
    row = second.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    second.close()
    assert row["status"] == "running"


def test_schema_task_records_required_fields(conn: sqlite3.Connection) -> None:
    task_id = add_task(conn, add_repository(conn))
    conn.execute(
        "UPDATE tasks SET branch = ?, worktree_path = ?, base_commit = ? WHERE id = ?",
        ("agent/template-sync-1", "/agent-worktrees/sample/template-sync-1", "abc123", task_id),
    )
    row = conn.execute(
        "SELECT t.id, r.name AS repository, t.workflow, t.branch, t.worktree_path, t.status,"
        " t.created_at, t.updated_at FROM tasks t"
        " JOIN repositories r ON r.id = t.repository_id WHERE t.id = ?",
        (task_id,),
    ).fetchone()
    assert dict(row) == {
        "id": task_id,
        "repository": "sample",
        "workflow": "template-sync",
        "branch": "agent/template-sync-1",
        "worktree_path": "/agent-worktrees/sample/template-sync-1",
        "status": "queued",
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_schema_task_worktree_fields_are_empty_until_the_worktree_exists(
    conn: sqlite3.Connection,
) -> None:
    task_id = add_task(conn, add_repository(conn))
    row = conn.execute(
        "SELECT branch, worktree_path, base_commit FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    assert tuple(row) == (None, None, None)


def test_schema_accepts_every_task_status(conn: sqlite3.Connection) -> None:
    repository_id = add_repository(conn)
    for status in TASK_STATUSES:
        add_task(conn, repository_id, status=status)
    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == len(TASK_STATUSES)


def test_schema_rejects_unknown_task_status(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_task(conn, add_repository(conn), status="paused")


def test_schema_accepts_every_event_kind(conn: sqlite3.Connection) -> None:
    task_id = add_task(conn, add_repository(conn))
    for seq, kind in enumerate(EVENT_KINDS, start=1):
        add_event(conn, task_id, seq, kind)
    assert conn.execute("SELECT count(*) FROM task_events").fetchone()[0] == len(EVENT_KINDS)


def test_schema_rejects_unknown_event_kind(conn: sqlite3.Connection) -> None:
    task_id = add_task(conn, add_repository(conn))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_event(conn, task_id, 1, "thinking")


def test_schema_rejects_duplicate_event_seq_for_a_task(conn: sqlite3.Connection) -> None:
    task_id = add_task(conn, add_repository(conn))
    add_event(conn, task_id, 1)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_event(conn, task_id, 1)


def test_schema_rejects_duplicate_repository_name(conn: sqlite3.Connection) -> None:
    add_repository(conn, "sample")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_repository(conn, "sample")


def test_schema_rejects_task_for_unknown_repository(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        add_task(conn, repository_id=999)


def test_schema_never_reuses_task_ids(conn: sqlite3.Connection) -> None:
    repository_id = add_repository(conn)
    add_task(conn, repository_id)
    last = add_task(conn, repository_id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (last,))
    assert add_task(conn, repository_id) == last + 1


# ---------------------------------------------------------------- app startup


def test_app_startup_migrates_the_database(settings: Settings) -> None:
    with TestClient(create_app(settings)):
        pass
    connection = db.connect(settings.database_path)
    try:
        assert user_version(connection) == len(db.MIGRATIONS)
    finally:
        connection.close()
