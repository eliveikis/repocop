"""Requests to sessions: from a requirement's page, the developer asks one of its live sessions
to run one of the repository's committed workflows on it ("Session requests" in
`specs/architecture.md`).

A request names only the workflow and the requirement's path, and goes only on the developer's
click. A session that is working, or needs input, gets it when its turn ends: it waits as
`<git common dir>/repocop/inbox/<session id>.json`, where it can be cancelled, until the session's
own hook takes it, once, and records it delivered beside it. A session waiting for an instruction
gets it at once, through the inbox socket its agent listens on, and starts its next turn with it.
A socket is taken from the session's log only when it is a socket of this user's, named after
the session's own process, in a folder no one else can write.
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG, S_ISSOCK
from typing import Any

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import sessions, tasks
from repocop.services.repositories import Repository
from repocop.services.sessions import Session, State

INBOX = PurePosixPath("repocop", "inbox")  # in the repository's git common folder
NOT_STARTED_AFTER = timedelta(minutes=3)  # how long a delivered workflow may take to start
SEND_TIMEOUT_S = 2.0  # how long handing a request to a session's socket may take
REQUEST_BYTES = 4096  # the most of a request file that is read
GONE = "No request waits for it any more: it was handed over, or is gone."


class RequestError(RepoCopError):
    """A request can't be sent, cancelled or handed over as asked."""


@dataclass(frozen=True)
class Request:
    id: str
    workflow: str
    requirement: str  # its path, relative to the checkout
    at: datetime  # when it was asked for, or, once delivered, when it was delivered


@dataclass(frozen=True)
class Standing:
    """Where a session's request stands: the one waiting for it, and the one last delivered."""

    waiting: Request | None
    delivered: Request | None
    started: bool  # the session started the delivered workflow after it was delivered
    late: bool  # delivered a while ago, but its workflow hasn't started


def instruction(workflow: str, requirement: str) -> str:
    """What the session is told: to run the workflow's skill on the requirement."""
    return (
        f"The developer asks, from RepoCop: run the `{workflow}` skill with the argument "
        f"`{requirement}`."
    )


def unreachable(session: Session) -> str | None:
    """Why the session can't be sent a request, or None when it can."""
    if session.state is State.CLOSED:
        return "It has closed."
    if session.state is State.STOPPED:
        return "Its process ended mid-turn. Resume it, then run the line in it."
    if session.socket is None:
        return (
            "Its repository's template doesn't hand sessions requests yet: a template sync "
            "brings it, for sessions started on a branch that has it."
        )
    if session.state is State.WAITING and session.running is False:
        return (
            "Its process isn't running: agent view has put it to sleep, or it ended. Run the line "
            "in it, which wakes it."
        )
    return None


def standing(
    repository: Repository, settings: Settings, session: Session, *, now: datetime | None = None
) -> Standing:
    """Where the session's request stands, read from its inbox."""
    folder = _inbox(repository, settings)
    if folder is None:
        return Standing(None, None, False, False)
    waiting = _read(folder / f"{session.id}.json")
    delivered = _read(folder / f"{session.id}.delivered.json")
    started = (
        delivered is not None
        and session.workflow == delivered.workflow
        and session.workflow_at is not None
        and session.workflow_at >= delivered.at
    )
    waited = (now or _now()) - delivered.at if delivered else timedelta(0)
    return Standing(waiting, delivered, started, not started and waited > NOT_STARTED_AFTER)


def send(
    repository: Repository,
    settings: Settings,
    session: Session,
    workflow: str,
    requirement: str,
) -> Request:
    """Ask the session to run `workflow` on the requirement at `requirement`: at once, through
    its socket, when it waits for an instruction, else when its turn ends. Refused when it can't
    be reached, when the workflow isn't a skill committed in the repository, when the path can't
    be told to it as it is, and when another request waits for it already."""
    if reason := unreachable(session):
        raise RequestError(reason)
    if workflow not in tasks.workflows(settings, repository):
        raise RequestError(f"{workflow!r} isn't a skill committed in {repository.name}")
    if any(mark in requirement for mark in ("`", "\\", "\n", "\r")) or requirement.startswith("/"):
        raise RequestError(f"{requirement} can't be named in a request as it is")
    folder = _inbox(repository, settings, make=True)
    if folder is None:
        raise RequestError(f"{repository.name}'s checkout isn't there")
    request = Request(str(uuid.uuid4()), workflow, requirement, _now())
    if session.state is State.WAITING:
        _hand_over(folder, session, request)
        return request
    waiting = folder / f"{session.id}.json"
    _write(waiting, request, exclusive=True)
    # It may have finished its turn since it was read, and its hook may have looked already.
    now = sessions.get(repository, settings, session.id)
    if now is not None and now.state is State.WAITING and unreachable(now) is None:
        _take_and_hand_over(folder, now)
    return request


def send_waiting(repository: Repository, settings: Settings, session: Session) -> Request:
    """Hand the request waiting for the session over now, through its socket: for a session
    whose turn ended before its hook could see the request."""
    if reason := unreachable(session):
        raise RequestError(reason)
    if session.state is not State.WAITING:
        raise RequestError("It's still working: it gets the request when its turn ends.")
    folder = _inbox(repository, settings)
    if folder is None:
        raise RequestError(f"{repository.name}'s checkout isn't there")
    return _take_and_hand_over(folder, session)


def cancel(repository: Repository, settings: Settings, session: Session) -> None:
    """Withdraw the request waiting for the session. Refused once it has been taken."""
    folder = _inbox(repository, settings)
    waiting = folder / f"{session.id}.json" if folder else None
    withdrawn = waiting.with_name(f"{session.id}.withdrawn.{uuid.uuid4()}") if waiting else None
    try:
        if waiting is None or withdrawn is None:
            raise FileNotFoundError
        waiting.rename(withdrawn)
    except FileNotFoundError:
        raise RequestError(GONE) from None
    withdrawn.unlink(missing_ok=True)


def _inbox(repository: Repository, settings: Settings, *, make: bool = False) -> Path | None:
    """The repository's inbox folder, inside its git common folder, or None."""
    common = sessions.common_dir(repository, settings)
    if common is None:
        return None
    folder = common / INBOX
    if make:
        folder.mkdir(parents=True, exist_ok=True)
    if not folder.is_dir() or not folder.resolve().is_relative_to(common):
        return None
    return folder


def _take_and_hand_over(folder: Path, session: Session) -> Request:
    """Take the request waiting for the session, once, and hand it over through its socket."""
    waiting = folder / f"{session.id}.json"
    taking = folder / f"{session.id}.taking.{uuid.uuid4()}"
    try:
        waiting.rename(taking)
    except FileNotFoundError:
        raise RequestError(GONE) from None
    request = _read(taking)
    taking.unlink(missing_ok=True)
    if request is None:
        raise RequestError("The request waiting for it can't be read, so it was dropped.")
    _hand_over(folder, session, request)
    return request


def _hand_over(folder: Path, session: Session, request: Request) -> None:
    """Send the request through the session's socket, and record it delivered."""
    path = _socket(session)
    message = {
        "type": "user",
        "session_id": session.id,
        "priority": "later",  # after the current turn, if one has started meanwhile
        "from": "RepoCop",
        "uuid": request.id,
        "message": {"role": "user", "content": instruction(request.workflow, request.requirement)},
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(SEND_TIMEOUT_S)
            connection.connect(str(path))
            connection.sendall((json.dumps(message) + "\n").encode())
            connection.shutdown(socket.SHUT_WR)
    except OSError as exc:
        raise RequestError(f"The session couldn't be reached: {exc.strerror or exc}") from None
    delivered = Request(request.id, request.workflow, request.requirement, _now())
    _write(folder / f"{session.id}.delivered.json", delivered, exclusive=False)


def _socket(session: Session) -> Path:
    """The session's socket, refused unless it is a socket of this user's, named after the
    session's own process, in a folder no one else can write."""
    refused = RequestError("Its socket can't be trusted, so nothing was sent to it.")
    if session.socket is None or session.pid is None:
        raise refused
    path = Path(session.socket)
    if not path.is_absolute() or path.name != f"{session.pid}.sock":
        raise refused
    try:
        found, folder = os.lstat(path), os.lstat(path.parent)
    except OSError:
        raise RequestError("Its socket is gone: the session has ended or moved.") from None
    mine = os.getuid()
    if not S_ISSOCK(found.st_mode) or found.st_uid != mine:
        raise refused
    if not S_ISDIR(folder.st_mode) or folder.st_uid != mine or folder.st_mode & 0o022:
        raise refused
    return path


def _write(path: Path, request: Request, *, exclusive: bool) -> None:
    """Write the request at `path` whole, so no reader sees part of it. With `exclusive`,
    refused while one is there."""
    fields = {
        "v": 1,
        "id": request.id,
        "workflow": request.workflow,
        "requirement": request.requirement,
        "at": request.at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    draft = path.with_name(f"{path.name}.{uuid.uuid4()}.draft")
    draft.write_text(json.dumps(fields) + "\n")
    try:
        if exclusive:
            path.hardlink_to(draft)
        else:
            draft.replace(path)
    except FileExistsError:
        raise RequestError(
            "A request already waits for it. Cancel that one first, or let it be delivered."
        ) from None
    finally:
        draft.unlink(missing_ok=True)


def _read(path: Path) -> Request | None:
    """The request in the file at `path`, or None when there is none that can be read. Never
    through a link: any local process can write here."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as file:
        if not S_ISREG(os.fstat(file.fileno()).st_mode):
            return None
        data = file.read(REQUEST_BYTES)
    try:
        fields: Any = json.loads(data.decode("utf-8", "replace"))
        at = datetime.fromisoformat(str(fields["at"]))
    except (ValueError, RecursionError, TypeError, KeyError):
        return None
    texts = [fields.get(key) for key in ("id", "workflow", "requirement")]
    if not all(isinstance(text, str) and text for text in texts) or at.tzinfo is None:
        return None
    return Request(texts[0], texts[1], texts[2], at)


def _now() -> datetime:
    return datetime.now(UTC)
