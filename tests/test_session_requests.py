"""Requests to sessions: a workflow and a requirement, sent only to a session that can be
reached, at once through its socket when it waits for an instruction, else left waiting for its
turn to end, where it can be cancelled."""

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from repocop.config import Settings
from repocop.services import repositories, session_requests, sessions
from repocop.services.repositories import Repository
from repocop.services.session_requests import RequestError
from repocop.services.sessions import Session
from tests.conftest import OWN_START, SESSION, Inbox, add_requirement, record_session, run_git

REQUIREMENT = "specs/changes/todo/bulk-import.md"


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    """A repository with its `implement` skill and the bulk-import requirement committed."""
    repository = repositories.register(
        conn, settings, str(remote_repo), default_branch="main"
    ).repository
    skill = repository.primary_path / ".claude" / "skills" / "implement"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# implement\n")
    run_git("add", ".claude", cwd=repository.primary_path)
    run_git("commit", "-qm", "Add a skill", cwd=repository.primary_path)
    add_requirement(repository.primary_path, "bulk-import.md")
    return repository


def session(repo: Repository, settings: Settings, inbox: Inbox | None, *events: Any) -> Session:
    """The session after `events`, each in its socket's folder when one is given."""
    where = {"socket": str(inbox.path)} if inbox else {}
    record_session(repo.primary_path, *({**where, **event} for event in events))
    found = sessions.get(repo, settings, SESSION)
    assert found is not None
    return found


def waiting_file(repo: Repository) -> Path:
    return repo.primary_path / ".git" / "repocop" / "inbox" / f"{SESSION}.json"


def test_a_session_waiting_for_an_instruction_gets_the_request_at_once_through_its_socket(
    settings: Settings, repo: Repository, inbox_socket: Inbox
) -> None:
    idle = session(repo, settings, inbox_socket, {"event": "turn-finished", "ago": 5})
    sent = session_requests.send(repo, settings, idle, "implement", REQUIREMENT)
    [line] = inbox_socket.received()
    content = (
        f"The developer asks, from RepoCop: run the `implement` skill with the argument "
        f"`{REQUIREMENT}`."
    )
    assert line == {
        "type": "user",
        "session_id": SESSION,
        "priority": "later",
        "from": "RepoCop",
        "uuid": sent.id,
        "message": {"role": "user", "content": content},
    }
    assert not waiting_file(repo).exists()
    standing = session_requests.standing(repo, settings, idle)
    assert standing.waiting is None
    assert standing.delivered is not None and standing.delivered.workflow == "implement"
    assert not standing.started
    after = {"event": "workflow", "workflow": "implement", "ago": -10}  # NOW is when tests began
    started = session(repo, settings, inbox_socket, after)
    assert session_requests.standing(repo, settings, started).started


def test_a_working_session_gets_the_request_when_its_turn_ends_and_it_can_be_cancelled(
    settings: Settings, repo: Repository, inbox_socket: Inbox
) -> None:
    working = session(repo, settings, inbox_socket, {"event": "working", "ago": 2})
    sent = session_requests.send(repo, settings, working, "implement", REQUIREMENT)
    left = json.loads(waiting_file(repo).read_text())
    assert {key: left[key] for key in ("v", "id", "workflow", "requirement")} == {
        "v": 1,
        "id": sent.id,
        "workflow": "implement",
        "requirement": REQUIREMENT,
    }
    assert session_requests.standing(repo, settings, working).waiting == sent
    with pytest.raises(RequestError, match="already waits"):
        session_requests.send(repo, settings, working, "implement", REQUIREMENT)
    session_requests.cancel(repo, settings, working)
    assert session_requests.standing(repo, settings, working).waiting is None
    with pytest.raises(RequestError, match="No request waits"):
        session_requests.cancel(repo, settings, working)
    assert inbox_socket.received() == []


def test_a_request_left_as_the_turn_ends_is_handed_over_rather_than_left_waiting(
    settings: Settings, repo: Repository, inbox_socket: Inbox
) -> None:
    as_read = session(repo, settings, inbox_socket, {"event": "working", "ago": 2})
    session(repo, settings, inbox_socket, {"event": "turn-finished", "ago": 1})  # since then
    session_requests.send(repo, settings, as_read, "implement", REQUIREMENT)
    assert not waiting_file(repo).exists()
    assert len(inbox_socket.received()) == 1


def test_a_request_still_waiting_once_the_turn_ended_can_be_sent_now(
    settings: Settings, repo: Repository, inbox_socket: Inbox
) -> None:
    working = session(repo, settings, inbox_socket, {"event": "working", "ago": 2})
    sent = session_requests.send(repo, settings, working, "implement", REQUIREMENT)
    with pytest.raises(RequestError, match="still working"):
        session_requests.send_waiting(repo, settings, working)
    idle = session(repo, settings, inbox_socket, {"event": "turn-finished", "ago": 1})
    assert session_requests.send_waiting(repo, settings, idle).id == sent.id
    assert [line["uuid"] for line in inbox_socket.received()] == [sent.id]
    assert not waiting_file(repo).exists()


@pytest.mark.parametrize(
    ("events", "with_socket", "reason"),
    [
        ([{"event": "closed", "reason": "exit"}], True, "closed"),
        ([{"event": "working", "pid_start": "1"}], True, "ended mid-turn"),
        ([{"event": "turn-finished", "pid_start": "1"}], True, "isn't running"),
        ([{"event": "turn-finished"}], False, "doesn't hand sessions requests yet"),
    ],
    ids=["closed", "stopped", "asleep", "old-template"],
)
def test_a_session_that_cant_be_reached_says_why_and_gets_nothing(
    settings: Settings,
    repo: Repository,
    inbox_socket: Inbox,
    events: list[dict[str, Any]],
    with_socket: bool,
    reason: str,
) -> None:
    if OWN_START is None and any("pid_start" in event for event in events):
        pytest.skip("a process's end is only told where /proc shows processes")
    found = session(repo, settings, inbox_socket if with_socket else None, *events)
    assert reason in (session_requests.unreachable(found) or "")
    with pytest.raises(RequestError, match=reason):
        session_requests.send(repo, settings, found, "implement", REQUIREMENT)
    assert inbox_socket.received() == []
    assert not waiting_file(repo).exists()


@pytest.mark.parametrize(
    ("workflow", "requirement", "refusal"),
    [
        ("review-branch", REQUIREMENT, "isn't a skill committed"),
        ("implement", "specs/changes/todo/x`; push`.md", "can't be named"),
        ("implement", "/etc/passwd", "can't be named"),
    ],
)
def test_a_request_names_only_a_committed_workflow_and_a_requirement_path(
    settings: Settings,
    repo: Repository,
    inbox_socket: Inbox,
    workflow: str,
    requirement: str,
    refusal: str,
) -> None:
    idle = session(repo, settings, inbox_socket, {"event": "turn-finished"})
    with pytest.raises(RequestError, match=refusal):
        session_requests.send(repo, settings, idle, workflow, requirement)
    assert inbox_socket.received() == []


@pytest.mark.parametrize("trap", ["named-for-another-process", "a-file", "an-open-folder"])
def test_nothing_is_sent_to_a_socket_that_cant_be_trusted(
    settings: Settings, repo: Repository, inbox_socket: Inbox, tmp_path: Path, trap: str
) -> None:
    path = inbox_socket.path
    if trap == "named-for-another-process":
        path = path.with_name("1.sock")
        path.symlink_to(inbox_socket.path)
    elif trap == "a-file":
        path = tmp_path / f"{os.getpid()}.sock"
        path.write_text("")
    else:
        path.parent.chmod(0o777)
    idle = session(repo, settings, None, {"event": "turn-finished", "socket": str(path)})
    try:
        with pytest.raises(RequestError, match="can't be trusted"):
            session_requests.send(repo, settings, idle, "implement", REQUIREMENT)
    finally:
        inbox_socket.path.parent.chmod(0o700)
    assert inbox_socket.received() == []


def test_a_delivered_request_whose_workflow_hasnt_started_in_minutes_is_late(
    settings: Settings, repo: Repository, inbox_socket: Inbox
) -> None:
    idle = session(repo, settings, inbox_socket, {"event": "turn-finished", "ago": 9})
    session_requests.send(repo, settings, idle, "implement", REQUIREMENT)
    assert not session_requests.standing(repo, settings, idle).late
    later = datetime.now(UTC) + timedelta(minutes=4)
    assert session_requests.standing(repo, settings, idle, now=later).late
