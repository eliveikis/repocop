"""Sessions as RepoCop reads them from a repository's session logs: each one's state and how long
it has been in it, the requirement it works on, and what is never read."""

import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from repocop.config import Settings
from repocop.services import repositories, sessions
from repocop.services.repositories import Repository
from repocop.services.sessions import Session, State
from tests.conftest import NOW, OWN_START, SESSION, add_requirement, record_session


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo), default_branch="main").repository


def write(repo: Repository, *events: dict[str, Any], session: str = SESSION) -> Path:
    return record_session(repo.primary_path, *events, session=session)


def only(settings: Settings, repo: Repository) -> Session:
    [found] = sessions.of(repo, settings, now=NOW)
    return found


@pytest.mark.parametrize(
    ("events", "state", "minutes"),
    [
        ([{"event": "started", "ago": 9}], State.WAITING, 9),
        ([{"event": "started", "ago": 9}, {"event": "working", "ago": 5}], State.WORKING, 5),
        (
            [
                {"event": "started", "ago": 9},
                {"event": "workflow", "ago": 5, "workflow": "implement"},
            ],
            State.WORKING,
            5,
        ),
        (
            [
                {"event": "working", "ago": 9},
                {"event": "waiting", "ago": 4, "waiting_for": "permission", "tool": "Bash"},
                {"event": "waiting", "ago": 2, "waiting_for": "permission"},
            ],
            State.NEEDS_INPUT,
            4,
        ),
        (
            [
                {"event": "working", "ago": 9},
                {"event": "turn-finished", "ago": 3},
                {"event": "moved", "ago": 1},
            ],
            State.WAITING,
            3,
        ),
        ([{"event": "working", "ago": 9}, {"event": "closed", "ago": 2}], State.CLOSED, 2),
    ],
    ids=["started", "working", "workflow", "needs-input", "turn-finished", "closed"],
)
def test_a_sessions_state_is_the_one_its_events_put_it_in_since_it_went_into_it(
    settings: Settings,
    repo: Repository,
    events: list[dict[str, Any]],
    state: State,
    minutes: int,
) -> None:
    write(repo, *events)
    found = only(settings, repo)
    assert (found.state, found.since) == (state, NOW - timedelta(minutes=minutes))
    assert found.last_at == NOW - timedelta(minutes=events[-1]["ago"])


def test_a_session_waiting_for_permission_names_the_tool_until_it_works_again(
    settings: Settings, repo: Repository
) -> None:
    write(
        repo,
        {"event": "waiting", "ago": 4, "waiting_for": "permission", "tool": "Bash"},
        {"event": "waiting", "ago": 3, "waiting_for": "permission"},  # its notification
    )
    found = only(settings, repo)
    assert (found.waiting_for, found.tool) == ("permission", "Bash")
    write(repo, {"event": "working", "ago": 2}, {"event": "waiting", "waiting_for": "answer"})
    found = only(settings, repo)
    assert (found.state, found.waiting_for, found.tool) == (State.NEEDS_INPUT, "answer", None)


@pytest.mark.parametrize(
    ("reason", "how"),
    [("clear", "was cleared"), ("logout", "was logged out"), ("prompt_input_exit", "exited")],
)
def test_a_closed_session_says_how_it_closed(
    settings: Settings, repo: Repository, reason: str, how: str
) -> None:
    write(repo, {"event": "started", "ago": 5}, {"event": "closed", "reason": reason})
    found = only(settings, repo)
    assert (found.state, found.closed) == (State.CLOSED, how)


@pytest.mark.parametrize(
    ("last", "state"),
    [
        ({"event": "working"}, State.STOPPED),
        ({"event": "waiting", "waiting_for": "answer"}, State.STOPPED),
        ({"event": "turn-finished"}, State.WAITING),  # asleep, as agent view leaves it
        ({"event": "closed", "reason": "exit"}, State.CLOSED),
    ],
    ids=["working", "needs-input", "turn-finished", "closed"],
)
def test_a_session_whose_process_ended_mid_turn_is_stopped_mid_turn(
    settings: Settings, repo: Repository, last: dict[str, Any], state: State
) -> None:
    if OWN_START is None:
        pytest.skip("a process's end is only told where /proc shows processes")
    ended = {"pid": os.getpid(), "pid_start": str(int(OWN_START) + 1)}  # the id, reused
    write(repo, {"event": "started", "ago": 9, **ended}, {"ago": 2, **last, **ended})
    found = only(settings, repo)
    assert found.state is state
    if state is State.STOPPED:
        assert found.since == NOW - timedelta(minutes=2)


def test_a_workflow_names_its_requirement_whatever_its_file_is_called(
    settings: Settings, repo: Repository
) -> None:
    add_requirement(repo.primary_path, "fix.md")
    add_requirement(repo.primary_path, "fix #42 at 50%?.md")
    for argument, named in (
        ('"specs/changes/todo/fix #42 at 50%?.md" and more', "fix #42 at 50%?"),
        ("specs/changes/todo/fix.md", "fix"),
        ("specs/changes/todo/gone.md", None),  # named no requirement there is: its branch's
    ):
        write(repo, {"event": "workflow", "workflow": "implement", "argument": argument})
        assert only(settings, repo).requirement == named, argument


def test_a_sessions_requirement_is_the_one_its_latest_workflow_named(
    settings: Settings, repo: Repository
) -> None:
    add_requirement(repo.primary_path, "bulk-import.md")
    add_requirement(repo.primary_path, "req-7-search.md")
    path = "specs/changes/todo/req-7-search.md"
    write(
        repo,
        {"event": "workflow", "workflow": "implement", "argument": "specs/changes/todo/x.md"},
        {"event": "workflow", "workflow": "address-review", "argument": f"{path} .reviews/r.md"},
        {"event": "turn-finished", "branch": "agent/bulk-import"},
    )
    found = only(settings, repo)
    assert (found.requirement, found.page, found.workflow) == (
        "search",
        "req-7-search.md",
        "address-review",
    )


@pytest.mark.parametrize(
    ("branch", "named"),
    [
        ("bulk-import", ("bulk-import", "bulk-import.md")),
        ("agent/bulk-import", ("bulk-import", "bulk-import.md")),
        ("req-7-search", ("search", "req-7-search.md")),
        ("done", ("done", "done.md")),  # archived since
        ("main", (None, None)),
    ],
)
def test_without_a_named_requirement_a_session_works_on_its_branchs(
    settings: Settings, repo: Repository, branch: str, named: tuple[str | None, str | None]
) -> None:
    add_requirement(repo.primary_path, "bulk-import.md")
    add_requirement(repo.primary_path, "req-7-search.md")
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir(parents=True)
    (archive / "2026-10-14T150616Z-done.md").write_text("Done.\n")
    write(
        repo,
        {"event": "workflow", "workflow": "address-review", "argument": "", "branch": "main"},
        {"event": "turn-finished", "branch": branch},
    )
    found = only(settings, repo)
    assert (found.requirement, found.page) == named


def test_only_sessions_with_an_event_in_the_past_day_show_the_latest_first(
    settings: Settings, repo: Repository
) -> None:
    write(repo, {"event": "started", "ago": 25 * 60}, session="old")
    write(repo, {"event": "started", "ago": 25 * 60}, {"event": "working", "ago": 30}, session="a")
    write(repo, {"event": "started", "ago": 10}, session="b")
    assert [found.id for found in sessions.of(repo, settings, now=NOW)] == ["b", "a"]


def test_a_live_session_shows_however_many_newer_sessions_there_are(
    settings: Settings, repo: Repository
) -> None:
    quiet = write(repo, {"event": "turn-finished", "ago": 600}, session="quiet")
    hours_ago = (NOW - timedelta(hours=10)).timestamp()
    os.utime(quiet, (hours_ago, hours_ago))
    for number in range(250):
        write(repo, {"event": "closed", "ago": 1}, session=f"done-{number}")
    shown = {found.id: found.state for found in sessions.of(repo, settings, now=NOW)}
    assert len(shown) == 251
    assert shown["quiet"] is State.WAITING


def test_lines_that_cant_be_read_are_skipped(settings: Settings, repo: Repository) -> None:
    log = write(repo, {"event": "started", "ago": 9})
    with log.open("a") as file:
        file.write("not json\n[1, 2]\n" + "[" * 100_000 + "\n")
        for broken in (
            {"v": 2, "event": "working"},
            {"session": "someone-else", "event": "working"},
            {"event": "thinking"},
            {"event": ["working"]},
            {"event": {"working": 1}},
            {"event": "working", "at": "yesterday"},
            {"event": "working", "cwd": 7},
        ):
            line = {"v": 1, "at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": SESSION}
            file.write(json.dumps({**line, "cwd": "/x", **broken}) + "\n")
        file.write('{"v": 1, "at": "' + NOW.strftime("%Y-%m-%dT%H:%M:%SZ") + '", "sess')
    assert only(settings, repo).state is State.WAITING


def test_a_log_is_first_read_back_to_its_latest_workflow_and_no_further_than_read_back(
    settings: Settings, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    filler = {"event": "moved", "ago": 30, "cwd": "/x" * 500}
    write(repo, {"event": "workflow", "ago": 40, "workflow": "implement"}, *[filler] * 200)
    write(repo, {"event": "waiting", "ago": 1, "waiting_for": "answer"})
    found = only(settings, repo)
    assert (found.state, found.workflow) == (State.NEEDS_INPUT, "implement")
    monkeypatch.setattr(sessions, "READ_BACK", 64 * 1024)
    write(repo, *[filler] * 200, session="other")
    write(repo, {"event": "waiting", "ago": 1, "waiting_for": "answer"}, session="other")
    [other] = [found for found in sessions.of(repo, settings, now=NOW) if found.id == "other"]
    assert (other.state, other.workflow) == (State.NEEDS_INPUT, None)


def test_events_take_their_place_by_their_time_not_where_they_land_in_the_log(
    settings: Settings, repo: Repository
) -> None:
    write(repo, {"event": "working", "ago": 1}, {"event": "waiting", "ago": 2, "tool": "Bash"})
    assert only(settings, repo).state is State.WORKING
    write(repo, {"event": "waiting", "ago": 3, "waiting_for": "permission"})  # read on from here
    assert (only(settings, repo).state, only(settings, repo).since) == (
        State.WORKING,
        NOW - timedelta(minutes=1),
    )
    write(repo, {"event": "turn-finished", "ago": 0.5}, {"event": "workflow", "ago": 4})
    found = only(settings, repo)
    assert (found.state, found.since) == (State.WAITING, NOW - timedelta(minutes=0.5))


def test_a_log_written_anew_is_read_anew(settings: Settings, repo: Repository) -> None:
    log = write(repo, {"event": "working", "ago": 2})
    assert only(settings, repo).state is State.WORKING
    log.unlink()
    write(repo, {"event": "started", "ago": 9})
    assert only(settings, repo).state is State.WAITING


def test_a_log_that_leads_outside_the_folder_is_never_read(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_text(write(repo, {"event": "started"}).read_text())
    folder = repo.primary_path / ".git" / "repocop" / "sessions"
    (folder / f"{SESSION}.jsonl").unlink()
    (folder / f"{SESSION}.jsonl").symlink_to(elsewhere)
    assert sessions.of(repo, settings, now=NOW) == []
    folder.rename(tmp_path / "moved")
    folder.symlink_to(tmp_path / "moved")
    assert sessions.of(repo, settings, now=NOW) == []


def test_a_missing_checkout_has_no_sessions(settings: Settings, repo: Repository) -> None:
    write(repo, {"event": "started"})
    repo.primary_path.rename(repo.primary_path.with_name("moved"))
    assert sessions.of(repo, settings, now=NOW) == []
