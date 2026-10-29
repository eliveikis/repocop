"""Sessions: the developer's agent sessions in a repository, read from the logs its sessions write
("Session events" in `specs/architecture.md`).

Each session appends one JSON line per event to `<git common dir>/repocop/sessions/<id>.jsonl`.
A session shows while it has an event in the past day. Its state comes from its events and from
whether its process still runs, and its requirement from the workflow it last started or else its
branch. Once a repository's git common folder is known, reading costs no git call: only each log's
last part is read, and a line that can't be read is skipped. Any local process can write a log, so
its path must stay in the folder, and what it says is shown escaped.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from typing import Any

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import backlog, git, repositories, requirements
from repocop.services.repositories import Repository

FORMAT = 1  # the version of the log format read here
SHOWN_FOR = timedelta(days=1)  # how long after its last event a session still shows
TAIL_BYTES = 64 * 1024  # how much of the end of each log is read
LOGS_READ = 200  # the most logs read in one repository, most recently written first
LOGS = PurePosixPath("repocop", "sessions")  # in the repository's git common folder
# The hook the repo template ships, which records sessions, and the settings that run it.
RECORDER = ".claude/hooks/session-events.sh"
RECORDER_SETTINGS = ".claude/settings.json"
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
EVENTS = frozenset(
    {"started", "moved", "workflow", "waiting", "working", "turn-finished", "closed"}
)
HOW_CLOSED = {"clear": "was cleared", "logout": "was logged out"}  # else it exited

_COMMON_DIRS: dict[Path, Path] = {}  # each primary checkout's git common folder, once known
_COMMON_DIRS_GUARD = threading.Lock()
READINGS_KEPT = 5000  # the most logs whose reading is kept, so an unchanged log isn't read again
_READINGS: dict[Path, tuple[tuple[int, int], _Reading | None]] = {}
_READINGS_GUARD = threading.Lock()


class State(StrEnum):
    WORKING = "Working"
    NEEDS_INPUT = "Needs input"
    WAITING = "Waiting for instruction"
    STOPPED = "Stopped mid-turn"
    CLOSED = "Closed"

    @property
    def slug(self) -> str:
        return self.value.lower().replace(" ", "-")


LIVE = frozenset({State.WORKING, State.NEEDS_INPUT, State.WAITING})
_STATE_OF = {
    "started": State.WAITING,
    "working": State.WORKING,
    "workflow": State.WORKING,
    "waiting": State.NEEDS_INPUT,
    "turn-finished": State.WAITING,
    "closed": State.CLOSED,
}


@dataclass(frozen=True)
class Session:
    id: str
    repository_id: int
    state: State
    since: datetime  # when it went into its state
    last_at: datetime  # its latest event
    cwd: str  # the folder of its latest event
    branch: str | None  # the branch of its latest event
    workflow: str | None  # the workflow it last started
    requirement: str | None  # the name of the requirement it works on
    page: str | None  # the file name the requirement's page is found by
    waiting_for: str | None  # while it needs input: "permission" or "answer"
    tool: str | None  # the tool a permission wait is for, when known
    closed: str | None  # how it closed: "exited", "was cleared" or "was logged out"

    @property
    def live(self) -> bool:
        """Whether the work goes on: it is working, needs input or waits for an instruction."""
        return self.state in LIVE


@dataclass(frozen=True)
class _Event:
    at: datetime
    event: str
    cwd: str
    branch: str | None
    pid: int | None
    pid_start: str | None
    fields: dict[str, Any]

    def text(self, name: str) -> str | None:
        value = self.fields.get(name)
        return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class _Reading:
    """What a log says, before its process and its requirement are looked at."""

    latest: _Event
    state: State
    since: datetime
    workflow: str | None
    argument: str | None  # the latest workflow's, "" when it had none; None with no workflow
    waiting_for: str | None
    tool: str | None
    closed: str | None


def of(repository: Repository, settings: Settings, *, now: datetime | None = None) -> list[Session]:
    """The repository's sessions with an event in the past day, the latest first. None while its
    checkout isn't there."""
    common = _common_dir(repository, settings)
    if common is None:
        return []
    folder = common / LOGS
    if not folder.is_dir() or not folder.resolve().is_relative_to(common):
        return []
    now = now or datetime.now(UTC)
    pages = _requirement_pages(repository)
    found = []
    for log, written in _recent_logs(folder, now):
        reading = _reading(log, written)
        if reading is not None and now - reading.latest.at <= SHOWN_FOR:
            found.append(_session(repository, log.name.removesuffix(".jsonl"), reading, pages))
    return sorted(found, key=lambda session: session.last_at, reverse=True)


def for_requirement(found: Iterable[Session], name: str) -> tuple[Session, ...]:
    """Those of `found` that work on the requirement called `name`."""
    return tuple(session for session in found if session.requirement == name)


def recorder_on_origin(repository: Repository, settings: Settings) -> bool | None:
    """Whether the default branch on `origin`, as last fetched, has the hook that records
    sessions and the settings that run it. None when it can't be read."""
    try:
        checkout = repositories.require_checkout(repository, settings)
        files = git.read_files(
            checkout, repositories.origin_default(repository), [RECORDER, RECORDER_SETTINGS]
        )
    except RepoCopError:
        return None
    runs = files[RECORDER_SETTINGS] or b""
    return files[RECORDER] is not None and PurePosixPath(RECORDER).name.encode() in runs


def _common_dir(repository: Repository, settings: Settings) -> Path | None:
    """The repository's git common folder, asked of git only the first time."""
    with _COMMON_DIRS_GUARD:
        known = _COMMON_DIRS.get(repository.primary_path)
    if known is not None:
        return known
    try:
        found = git.common_dir(repositories.require_checkout(repository, settings))
    except RepoCopError:
        return None
    with _COMMON_DIRS_GUARD:
        _COMMON_DIRS[repository.primary_path] = found
    return found


def _recent_logs(folder: Path, now: datetime) -> list[tuple[Path, tuple[int, int]]]:
    """The folder's logs written in the past day, the latest first, at most LOGS_READ, each with
    when it was last written and its size. A link is never read: it could lead anywhere."""
    oldest = (now - SHOWN_FOR).timestamp()
    found = []
    for entry in folder.iterdir():
        name = entry.name
        if not name.endswith(".jsonl") or not SESSION_ID.fullmatch(name.removesuffix(".jsonl")):
            continue
        try:
            stat = entry.lstat()
        except OSError:
            continue
        if not S_ISREG(stat.st_mode) or stat.st_mtime < oldest:
            continue
        found.append((stat.st_mtime_ns, stat.st_size, entry))
    found.sort(reverse=True)
    return [(entry, (written, size)) for written, size, entry in found[:LOGS_READ]]


def _reading(log: Path, written: tuple[int, int]) -> _Reading | None:
    """What the log says, read again only once it has been written to since it was last read."""
    with _READINGS_GUARD:
        known = _READINGS.get(log)
    if known is not None and known[0] == written:
        return known[1]
    reading = _read(log)
    with _READINGS_GUARD:
        if len(_READINGS) >= READINGS_KEPT:
            _READINGS.clear()
        _READINGS[log] = (written, reading)
    return reading


def _read(log: Path) -> _Reading | None:
    """What the last TAIL_BYTES of a log say, read from its end back only as far as needed: its
    latest event, the state its latest events put it in and since when, and the workflow it last
    started. A line that can't be read is skipped. None when no line can be read."""
    try:
        with log.open("rb") as file:
            size = file.seek(0, os.SEEK_END)
            start = max(0, size - TAIL_BYTES)
            file.seek(start)
            data = file.read(TAIL_BYTES)
    except OSError:
        return None
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # cut where the read began
    session = log.name.removesuffix(".jsonl")
    latest: _Event | None = None
    state: State | None = None
    since = None
    waiting_for = tool = closed = workflow = argument = None
    in_run = seen_workflow = False
    for line in reversed(lines):
        event = _event(line, session)
        if event is None:
            continue
        if latest is None:
            latest, in_run = event, True
        if event.event == "workflow" and not seen_workflow:
            workflow, argument = event.text("workflow"), event.text("argument") or ""
            seen_workflow = True
        if in_run and event.event != "moved":
            new = _STATE_OF[event.event]
            if state is None:
                state, waiting_for, tool = new, event.text("waiting_for"), event.text("tool")
                if event.event == "closed":
                    closed = HOW_CLOSED.get(event.text("reason") or "", "exited")
            elif new is not state:
                in_run = False
            elif tool is None and event.text("waiting_for") == waiting_for:
                tool = event.text("tool")
            if in_run:
                since = event.at
        if not in_run and seen_workflow:
            break
    if latest is None:
        return None
    return _Reading(
        latest,
        state or State.WAITING,
        since or latest.at,
        workflow,
        argument,
        waiting_for if state is State.NEEDS_INPUT else None,
        tool if state is State.NEEDS_INPUT else None,
        closed,
    )


def _event(line: bytes, session: str) -> _Event | None:
    try:
        found = json.loads(line.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    fields = {key: _clean(value) for key, value in found.items()}
    if fields.get("v") != FORMAT or fields.get("session") != session:
        return None
    if fields.get("event") not in EVENTS or not isinstance(fields.get("cwd"), str):
        return None
    try:
        at = datetime.fromisoformat(str(fields.get("at")))
    except ValueError:
        return None
    if at.tzinfo is None:
        return None
    pid, pid_start = fields.get("pid"), fields.get("pid_start")
    return _Event(
        at,
        fields["event"],
        fields["cwd"],
        fields["branch"] if isinstance(fields.get("branch"), str) else None,
        pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None,
        pid_start if isinstance(pid_start, str) and pid_start.isdigit() else None,
        fields,
    )


def _clean(value: Any) -> Any:
    """`value`, any string in it made to be shown: a lone surrogate from a cut escape replaced."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    return value


def _session(
    repository: Repository, session: str, reading: _Reading, pages: dict[str, tuple[str, str]]
) -> Session:
    """The session as it stands now: its log's reading, its process looked at again, since it can
    end without a word, and its requirement among those the repository has now."""
    latest, state, since = reading.latest, reading.state, reading.since
    if state in (State.WORKING, State.NEEDS_INPUT) and _ended(latest):
        state, since = State.STOPPED, latest.at
    named = _named(repository, reading.argument) if reading.argument is not None else None
    belongs = pages.get(latest.branch.rpartition("/")[2]) if latest.branch else None
    requirement, page = named or belongs or (None, None)
    return Session(
        id=session,
        repository_id=repository.id,
        state=state,
        since=since,
        last_at=latest.at,
        cwd=latest.cwd,
        branch=latest.branch,
        workflow=reading.workflow,
        requirement=requirement,
        page=page,
        waiting_for=reading.waiting_for if state is State.NEEDS_INPUT else None,
        tool=reading.tool if state is State.NEEDS_INPUT else None,
        closed=reading.closed if state is State.CLOSED else None,
    )


def _named(repository: Repository, argument: str) -> tuple[str, str] | None:
    """(name, page file) of the requirement whose path in the requirements folder the workflow's
    argument holds, if it holds one."""
    folder = re.escape(requirements.todo_dir(repository) + "/")
    found = re.search(folder + r"([^\s/\"'`]+\.md)", argument)
    return (backlog.name_of(found[1]), found[1]) if found else None


def _requirement_pages(repository: Repository) -> dict[str, tuple[str, str]]:
    """(name, page file) of each requirement in the repository's folder or its archive, by each
    name a branch may end in: its name, and its file name without `.md`."""
    todo, archived = requirements.files_on_disk(repository)
    pages: dict[str, tuple[str, str]] = {}
    for file in archived:
        stamp = requirements.ARCHIVE_STAMP.match(file)
        page = file[stamp.end() :] if stamp else file
        for alias in (backlog.name_of(file), page.removesuffix(".md")):
            pages[alias] = (backlog.name_of(file), page)
    for file in todo:
        for alias in (backlog.name_of(file), file.removesuffix(".md")):
            pages[alias] = (backlog.name_of(file), file)
    return pages


def _ended(event: _Event) -> bool:
    """Whether the process that wrote `event` has ended. Only where `/proc` shows processes:
    elsewhere, or with no process recorded, it can't be told."""
    if event.pid is None or event.pid_start is None or not Path("/proc/self/stat").exists():
        return False
    try:
        stat = Path(f"/proc/{event.pid}/stat").read_text()
    except OSError:
        return True
    fields = stat.rpartition(") ")[2].split()
    return len(fields) < 20 or fields[19] != event.pid_start
