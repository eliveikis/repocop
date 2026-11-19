"""Sessions: the developer's agent sessions in a repository, read from the logs their hook writes,
in the format "The session log" in `specs/sessions.md` states, and what each one shows, by the
rules there.

Each repository's git common folder is asked of git once and kept in memory, so from then on
reading costs no git call. Each reading lists the logs folder and skips the logs not
written in SHOWN_FOR, however many the rest are, since a session quiet for hours may still be
live. A log is first read from its end back to its latest workflow, at most READ_BACK bytes, then
only what is appended to it, so an unchanged log costs only the look at its size and time that
the listing took; one that is another file at its path, told by its first IDENTITY_BYTES, or is
shorter, is read anew. Events are taken in by their time, not their place in the log, and one
older than the event that last set a field leaves that field as it is. A line that can't be read
is skipped. A session's process is looked at each time, since it can end without a word, in
`/proc`, so elsewhere a session that stopped mid-turn can't be told.

A requirement's runs come from the repository's history of workflow runs and from every session
log, each read whole the first time and then only as far as it was appended to. Any local process
can write a log or the history, so its path must stay in the folder, it is read only as a regular
file, never through a link and without waiting on a pipe, and what it says is shown escaped.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from typing import Any, BinaryIO

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import backlog, git, repositories, requirements
from repocop.services.repositories import Repository

FORMAT = 1  # the version of the log format read here
SHOWN_FOR = timedelta(days=1)  # how long after its last event a session still shows
CHUNK = 64 * 1024  # how much of a log is read at a time
READ_BACK = 1024 * 1024  # how far back from its end a log is first read, for its latest workflow
IDENTITY_BYTES = 256  # the first bytes of a log, which tell it from another file at its path
LOGS = PurePosixPath("repocop", "sessions")  # in the repository's git common folder
HISTORY = PurePosixPath("repocop", "history.jsonl")  # every workflow run, in the same folder
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
READINGS_KEPT = 5000  # the most logs whose reading is kept, so only what's appended is read
_READINGS: dict[Path, _Reading] = {}
_READINGS_GUARD = threading.Lock()
_RUNS: dict[Path, _Logged] = {}  # what each file says of runs, as far as it was read
_RUNS_GUARD = threading.Lock()


class State(StrEnum):
    WORKING = "Working"
    NEEDS_INPUT = "Needs input"
    COMPLETED = "Completed"
    STOPPED = "Stopped mid-turn"
    CLOSED = "Closed"

    @property
    def slug(self) -> str:
        return self.value.lower().replace(" ", "-")


LIVE = frozenset({State.WORKING, State.NEEDS_INPUT, State.COMPLETED})
_STATE_OF = {
    "started": State.COMPLETED,
    "working": State.WORKING,
    "workflow": State.WORKING,
    "waiting": State.NEEDS_INPUT,
    "turn-finished": State.COMPLETED,
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
    workflow: str | None  # the workflow it last started, while it works on what that was for
    requirement: str | None  # the name of the requirement it works on
    page: str | None  # the file name the requirement's page is found by
    waiting_for: str | None  # while it needs input: "permission" or "answer"
    tool: str | None  # the tool a permission wait is for, when known
    closed: str | None  # how it closed: "exited", "was cleared" or "was logged out"
    workflow_at: datetime | None = None  # when it started that workflow
    pid: int | None = None  # its agent's process, as its latest event names it
    running: bool | None = None  # whether that process still runs; None where it can't be told
    socket: str | None = None  # where its agent takes messages, as its latest event names it

    @property
    def live(self) -> bool:
        """Whether the work goes on: it is working, needs input or has completed its turn."""
        return self.state in LIVE


@dataclass(frozen=True)
class Run:
    """A workflow a session started."""

    session: str
    at: datetime
    workflow: str
    argument: str  # the first line of its argument, "" when it had none
    branch: str | None  # the branch it started on


@dataclass(frozen=True)
class _Ran:
    """A run, with each branch its session was on from its start until its next run, the first
    first: as much as the file it was read from tells of what it was for."""

    run: Run
    branches: tuple[str | None, ...]


# Each branch a session was on since a workflow started: the branch, and when it was first and
# last seen there, the first seen first. The workflow's own branch comes first.
_Seen = tuple[tuple[str | None, datetime, datetime], ...]


@dataclass(frozen=True)
class _Mark:
    """What an event tells of runs: when it happened, its branch, and the run it started."""

    at: datetime
    branch: str | None
    run: Run | None


@dataclass(frozen=True)
class _Logged:
    """What a file says of runs as far as it has been read."""

    file: tuple[int, int, bytes]  # its device, inode and first bytes: another file differs
    end: int  # where reading stopped: just past a line's end
    written: int  # when it was last written, as of that read
    marks: tuple[_Mark, ...]  # by their time
    runs: list[_Ran]


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
    """What a log says as far as it has been read, before its process and its requirement are
    looked at. Each field holds what the latest event, by time, that bears on it says."""

    file: tuple[int, int, bytes]  # the log's device, inode and first bytes: another file differs
    end: int  # where reading stopped: just past a line's end
    written: int  # when the log was last written, as of that read
    latest: _Event | None
    state: State | None  # None until an event sets one
    since: datetime | None  # when it went into its state
    state_at: datetime | None  # when the event that last set its state happened
    workflow: str | None
    argument: str | None  # the latest workflow's, "" when it had none; None with no workflow
    workflow_at: datetime | None
    workflow_seen: _Seen  # where the session has been since its latest workflow, or since read
    waiting_for: str | None
    tool: str | None
    closed: str | None


def of(repository: Repository, settings: Settings, *, now: datetime | None = None) -> list[Session]:
    """The repository's sessions with an event in the past day, the latest first. None while its
    checkout isn't there."""
    common = common_dir(repository, settings)
    if common is None:
        return []
    folder = common / LOGS
    if not folder.is_dir() or not folder.resolve().is_relative_to(common):
        return []
    now = now or datetime.now(UTC)
    pages = _requirement_pages(repository)
    found = []
    for log, listed in _logs(folder, written_since=(now - SHOWN_FOR).timestamp()):
        reading = _reading(log, listed)
        latest = reading.latest if reading else None
        if reading and latest and now - latest.at <= SHOWN_FOR:
            session = log.name.removesuffix(".jsonl")
            found.append(_session(repository, session, reading, latest, pages))
    return sorted(found, key=lambda session: session.last_at, reverse=True)


def for_requirement(found: Iterable[Session], name: str) -> tuple[Session, ...]:
    """Those of `found` that work on the requirement called `name`."""
    return tuple(session for session in found if session.requirement == name)


def runs(repository: Repository, settings: Settings, name: str) -> list[Run]:
    """The workflows run on the requirement called `name`, the newest first: those the
    repository's history keeps, and those in its sessions' logs, which reach back before the
    history did, each once. A run is on the requirement its argument's path names, or else on the
    requirement of the first branch its session was on from its start that belongs to one, as
    far as its session's log, while it is there, or else the history tells."""
    picked = [run for run, was_for in _every_run(repository, settings) if was_for == name]
    return sorted(picked, key=lambda run: run.at, reverse=True)


def last_started(repository: Repository, settings: Settings, workflow: str) -> dict[str, datetime]:
    """When `workflow` was last started on each requirement it ran on, by the requirement's
    name, a run on a requirement as `runs` tells it."""
    found: dict[str, datetime] = {}
    for run, was_for in _every_run(repository, settings):
        if (
            was_for
            and run.workflow == workflow
            and (was_for not in found or found[was_for] < run.at)
        ):
            found[was_for] = run.at
    return found


def _every_run(repository: Repository, settings: Settings) -> list[tuple[Run, str | None]]:
    """Every run the repository's history and its sessions' logs keep, each once, with the name
    of the requirement it was for, if that can be told."""
    common = common_dir(repository, settings)
    if common is None:
        return []
    found: dict[tuple[str, datetime], _Ran] = {}
    history = common / HISTORY
    if history.parent.resolve().is_relative_to(common):
        for ran in _runs_in(history, None):
            found.setdefault((ran.run.session, ran.run.at), ran)
    folder = common / LOGS
    if folder.is_dir() and folder.resolve().is_relative_to(common):
        for log, _ in _logs(folder, written_since=0):
            for ran in _runs_in(log, log.name.removesuffix(".jsonl")):
                found[ran.run.session, ran.run.at] = ran  # its log tells more of what it was for
    pages = _requirement_pages(repository)
    return [(ran.run, _run_was_for(repository, ran, pages)) for ran in found.values()]


def history_kept_on_origin(repository: Repository, settings: Settings) -> bool | None:
    """Whether the hook on the default branch on `origin`, as last fetched, keeps the history of
    workflow runs. None when it can't be read, or there is no hook there."""
    files = _recorder_on_origin(repository, settings)
    hook = files[RECORDER] if files else None
    return None if hook is None else HISTORY.name.encode() in hook


def recorder_on_origin(repository: Repository, settings: Settings) -> bool | None:
    """Whether the default branch on `origin`, as last fetched, has the hook that records
    sessions and the settings that run it. None when it can't be read."""
    files = _recorder_on_origin(repository, settings)
    if files is None:
        return None
    runs = files[RECORDER_SETTINGS] or b""
    return files[RECORDER] is not None and PurePosixPath(RECORDER).name.encode() in runs


def _recorder_on_origin(
    repository: Repository, settings: Settings
) -> dict[str, bytes | None] | None:
    """The hook that records sessions, and the settings that run it, on the default branch on
    `origin` as last fetched, each None where it isn't there. None when they can't be read."""
    try:
        checkout = repositories.require_checkout(repository, settings)
        return git.read_files(
            checkout, repositories.origin_default(repository), [RECORDER, RECORDER_SETTINGS]
        )
    except RepoCopError:
        return None


def get(repository: Repository, settings: Settings, session: str) -> Session | None:
    """The repository's session `session`, while it has an event in the past day."""
    return next((found for found in of(repository, settings) if found.id == session), None)


def common_dir(repository: Repository, settings: Settings) -> Path | None:
    """The repository's git common folder, where its sessions' logs and requests are: asked of
    git only the first time. None while its checkout isn't there."""
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


def _logs(folder: Path, *, written_since: float) -> list[tuple[Path, os.stat_result]]:
    """The folder's logs written since `written_since`, a POSIX time, each with what a look at it
    found, however many there are: a session that hasn't written for hours may still be live. A
    link is never read: it could lead anywhere."""
    found = []
    for entry in folder.iterdir():
        name = entry.name
        if not name.endswith(".jsonl") or not SESSION_ID.fullmatch(name.removesuffix(".jsonl")):
            continue
        try:
            stat = entry.lstat()
        except OSError:
            continue
        if S_ISREG(stat.st_mode) and stat.st_mtime >= written_since:
            found.append((entry, stat))
    return found


def _reading(log: Path, listed: os.stat_result) -> _Reading | None:
    """What the log says now: unread while it is as `listed` found it when last read, else read
    only as far as it was appended to since, or anew when it is another file, or shorter, than
    then. None when it can't be opened as a regular file."""
    with _READINGS_GUARD:
        known = _READINGS.get(log)
    seen = (listed.st_size, listed.st_mtime_ns, listed.st_dev, listed.st_ino)
    if known and seen == (known.end, known.written, *known.file[:2]):
        return known
    with _opened(log) as opened:
        if opened is None:
            return None
        file, stat = opened
        unchanged = (stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino)
        if known and unchanged == (known.end, known.written, *known.file[:2]):
            return known
        same = known is not None and known.file == _identity(file, stat)
        session = log.name.removesuffix(".jsonl")
        if same and known and known.end <= stat.st_size:
            reading = _read_on(file, stat, known, session)
        else:
            reading = _read_anew(file, stat, session)
    with _READINGS_GUARD:
        if len(_READINGS) >= READINGS_KEPT:
            _READINGS.clear()
        _READINGS[log] = reading
    return reading


def _read_anew(file: BinaryIO, stat: os.stat_result, session: str) -> _Reading:
    """What the log says, read from its last complete line back until its latest workflow, or
    READ_BACK bytes."""
    file.seek(max(0, stat.st_size - CHUNK))
    tail = file.read()
    end = stat.st_size - (len(tail) - tail.rfind(b"\n") - 1) if b"\n" in tail else 0
    found: list[_Event] = []
    position, carried = end, b""
    while position > 0 and end - position < READ_BACK:
        start = max(0, position - CHUNK, end - READ_BACK)
        file.seek(start)
        lines = (file.read(position - start) + carried).split(b"\n")
        carried = lines.pop(0) if start > 0 else b""  # whole only with the chunk before it
        events = [event for line in lines if (event := _event(line, session))]
        found[:0] = events
        position = start
        if any(event.event == "workflow" for event in events):
            break
    empty = _Reading(
        file=_identity(file, stat),
        end=end,
        written=stat.st_mtime_ns,
        latest=None,
        state=None,
        since=None,
        state_at=None,
        workflow=None,
        argument=None,
        workflow_at=None,
        workflow_seen=(),
        waiting_for=None,
        tool=None,
        closed=None,
    )
    return _fold(empty, found, end, stat.st_mtime_ns)


@contextmanager
def _opened(path: Path) -> Iterator[tuple[BinaryIO, os.stat_result] | None]:
    """`path`, open to read, with what it is, while it is a regular file: never opened through a
    link, and without waiting on a pipe. None when it can't be opened as one."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        yield None
        return
    with os.fdopen(descriptor, "rb") as file:
        stat = os.fstat(file.fileno())
        yield (file, stat) if S_ISREG(stat.st_mode) else None


def _identity(file: BinaryIO, stat: os.stat_result) -> tuple[int, int, bytes]:
    """What tells a file from another at its path: its device and inode, which a new file can be
    given again, and its first bytes, which appending leaves as they are."""
    file.seek(0)
    return stat.st_dev, stat.st_ino, file.read(IDENTITY_BYTES)


def _read_on(file: BinaryIO, stat: os.stat_result, known: _Reading, session: str) -> _Reading:
    """`known`, with the complete lines written after where its reading stopped."""
    file.seek(known.end)
    data = file.read(stat.st_size - known.end)
    complete = data[: data.rfind(b"\n") + 1]
    events = [event for line in complete.split(b"\n") if (event := _event(line, session))]
    return _fold(known, events, known.end + len(complete), stat.st_mtime_ns)


def _fold(reading: _Reading, events: list[_Event], end: int, written: int) -> _Reading:
    """`reading`, with `events` taken in by their time, those at one time in the log's order. An
    event older than the one that last set a field leaves that field as it is."""
    latest, state, since, state_at = reading.latest, reading.state, reading.since, reading.state_at
    workflow, argument, workflow_at = reading.workflow, reading.argument, reading.workflow_at
    seen = reading.workflow_seen
    waiting_for, tool, closed = reading.waiting_for, reading.tool, reading.closed
    for event in sorted(events, key=lambda event: event.at):
        if latest is None or event.at >= latest.at:
            latest = event
        if event.event == "workflow" and (workflow_at is None or event.at >= workflow_at):
            workflow, argument = event.text("workflow"), event.text("argument") or ""
            workflow_at, seen = event.at, _seen_from(seen, event.at, event.branch)
        elif workflow_at is None or event.at >= workflow_at:  # a workflow may yet land before it
            seen = _seen_with(seen, event.branch, event.at, event.at)
        if event.event == "moved" or (state_at is not None and event.at < state_at):
            continue
        new = _STATE_OF[event.event]
        if event.event == "waiting":
            asked = event.text("waiting_for")
            same_wait = state is State.NEEDS_INPUT and asked == waiting_for
            tool = event.text("tool") or (tool if same_wait else None)
            waiting_for = asked
        if event.event == "closed":
            closed = HOW_CLOSED.get(event.text("reason") or "", "exited")
        if new is not state:
            since = event.at
        state, state_at = new, event.at
    return _Reading(
        reading.file,
        end,
        written,
        latest,
        state,
        since,
        state_at,
        workflow,
        argument,
        workflow_at,
        seen,
        waiting_for,
        tool,
        closed,
    )


def _runs_in(file: Path, session: str | None) -> list[_Ran]:
    """The runs `file` records: a log of the session `session`, each run with the branches its
    session went on to, or, with None, the history, each run with the branch it started on. Only
    what was appended since it was last read is read, or all of it when it is another file, or
    shorter, than then: only as a regular file, never through a link."""
    with _RUNS_GUARD:
        known = _RUNS.get(file)
    with _opened(file) as opened:
        if opened is None:
            return []
        handle, stat = opened
        if known and (stat.st_size, stat.st_mtime_ns) == (known.end, known.written):
            return known.runs
        identity = _identity(handle, stat)
        on = known is not None and known.file == identity and known.end <= stat.st_size
        start = known.end if known and on else 0
        handle.seek(start)
        data = handle.read(stat.st_size - start)
    complete = data[: data.rfind(b"\n") + 1]
    events = (event for line in complete.split(b"\n") if (event := _event(line, session)))
    new = [mark for event in events if (mark := _mark(event)).run or session is not None]
    marks = tuple(sorted((*(known.marks if known and on else ()), *new), key=lambda m: m.at))
    found = _runs_from(marks, follow=session is not None)
    logged = _Logged(identity, start + len(complete), stat.st_mtime_ns, marks, found)
    with _RUNS_GUARD:
        if len(_RUNS) >= READINGS_KEPT:
            _RUNS.clear()
        _RUNS[file] = logged
    return logged.runs


def _mark(event: _Event) -> _Mark:
    workflow = event.text("workflow") if event.event == "workflow" else None
    run = None
    if workflow:
        argument = event.text("argument") or ""
        run = Run(event.fields["session"], event.at, workflow, argument, event.branch)
    return _Mark(event.at, event.branch, run)


def _runs_from(marks: Iterable[_Mark], *, follow: bool) -> list[_Ran]:
    """The runs `marks` start, by their time, each with the branches its session went on to
    until its next run when `follow`, else with the branch it started on."""
    found: list[tuple[Run, _Seen]] = []
    for mark in marks:
        if mark.run:
            found.append((mark.run, ((mark.branch, mark.at, mark.at),)))
        elif follow and found:
            run, seen = found[-1]
            found[-1] = (run, _seen_with(seen, mark.branch, mark.at, mark.at))
    return [_Ran(run, _branches(seen)) for run, seen in found]


def _seen_with(seen: _Seen, branch: str | None, first: datetime, last: datetime) -> _Seen:
    """`seen`, with `branch` seen from `first` to `last`."""
    for index, (known, was_first, was_last) in enumerate(seen):
        if known == branch:
            widened = (branch, min(first, was_first), max(last, was_last))
            changed = (*seen[:index], widened, *seen[index + 1 :])
            return tuple(sorted(changed, key=lambda each: each[1]))
    return tuple(sorted((*seen, (branch, first, last)), key=lambda each: each[1]))


def _seen_from(seen: _Seen, at: datetime, branch: str | None) -> _Seen:
    """Where the session has been since a workflow started at `at` on `branch`, from `seen`: its
    own branch first, then each seen since, one also seen before it as if first seen at `at`.
    Hooks finish in any order, so a workflow may come to be read after what followed it."""
    since: _Seen = ((branch, at, at),)
    for other, first, last in seen:
        if last >= at:
            since = _seen_with(since, other, max(first, at), last)
    return since


def _branches(seen: _Seen) -> tuple[str | None, ...]:
    return tuple(branch for branch, _, _ in seen)


def _first_belonging(
    branches: Iterable[str | None], pages: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    """(name, page file) of the requirement of the first of `branches` that belongs to one: what
    a workflow that named none was for, as `/implement` starts on the default branch and then
    makes its own."""
    found = (_belongs(branch, pages) for branch in branches)
    return next((named for named in found if named), None)


def _run_was_for(
    repository: Repository, ran: _Ran, pages: dict[str, tuple[str, str]]
) -> str | None:
    """The name of the requirement `ran` was for, if it can be told."""
    argument = ran.run.argument
    named = _named(repository, argument, pages) if argument else None
    named = named or _first_belonging(ran.branches, pages)
    return named[0] if named else None


def _event(line: bytes, session: str | None) -> _Event | None:
    """The event `line` records for the session `session`, or for any session with None."""
    try:
        found = json.loads(line.decode("utf-8", "replace"))
    except (ValueError, RecursionError):  # not JSON, or nested too deep to read
        return None
    if not isinstance(found, dict):
        return None
    fields = {key: _clean(value) for key, value in found.items()}
    named = fields.get("session")
    if fields.get("v") != FORMAT or not isinstance(named, str):
        return None
    if (session is None and not SESSION_ID.fullmatch(named)) or session not in (None, named):
        return None
    event, cwd = fields.get("event"), fields.get("cwd")
    if not isinstance(event, str) or event not in EVENTS or not isinstance(cwd, str):
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
    repository: Repository,
    session: str,
    reading: _Reading,
    latest: _Event,
    pages: dict[str, tuple[str, str]],
) -> Session:
    """The session as it stands now: its log's reading, its process looked at again, since it can
    end without a word, and its requirement among those the repository has now."""
    state, since = reading.state or State.COMPLETED, reading.since or latest.at
    running = _running(latest)
    if state in (State.WORKING, State.NEEDS_INPUT) and running is False:
        state, since = State.STOPPED, latest.at
    named = _named(repository, reading.argument, pages) if reading.argument else None
    belongs = _belongs(latest.branch, pages)
    requirement, page = named or belongs or (None, None)
    workflow, workflow_at = reading.workflow, reading.workflow_at
    if not named and _first_belonging(_branches(reading.workflow_seen), pages) != belongs:
        workflow = workflow_at = None  # it was for other work, before the session moved on
    return Session(
        id=session,
        repository_id=repository.id,
        state=state,
        since=since,
        last_at=latest.at,
        cwd=latest.cwd,
        branch=latest.branch,
        workflow=workflow,
        requirement=requirement,
        page=page,
        waiting_for=reading.waiting_for if state is State.NEEDS_INPUT else None,
        tool=reading.tool if state is State.NEEDS_INPUT else None,
        closed=reading.closed if state is State.CLOSED else None,
        workflow_at=workflow_at,
        pid=latest.pid,
        running=running,
        socket=latest.text("socket"),
    )


def _belongs(branch: str | None, pages: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """(name, page file) of the requirement `branch` belongs to, if it belongs to one."""
    return pages.get(branch.rpartition("/")[2]) if branch else None


def _named(
    repository: Repository, argument: str, pages: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    """(name, page file) of the requirement whose path in the requirements folder the workflow's
    argument holds, if it holds one: the longest, as a file's name may hold anything, spaces
    and all."""
    folder = requirements.todo_dir(repository)
    held = [
        (len(page), named)
        for named in set(pages.values())
        if f"{folder}/{(page := named[1])}" in argument
    ]
    return max(held)[1] if held else None


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


def _running(event: _Event) -> bool | None:
    """Whether the process that wrote `event` still runs. None where `/proc` doesn't show
    processes, or no process was recorded: it can't be told."""
    if event.pid is None or event.pid_start is None or not Path("/proc/self/stat").exists():
        return None
    try:
        stat = Path(f"/proc/{event.pid}/stat").read_text()
    except OSError:
        return False
    fields = stat.rpartition(") ")[2].split()
    return len(fields) >= 20 and fields[19] == event.pid_start
