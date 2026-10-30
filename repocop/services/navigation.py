"""What the navigation every page shares shows: the registered repositories, the sessions that
need input, the session lists a page shows as they are now, and the repositories, requirements
and template syncs that a search finds. Sessions are read from their logs, without git once each
repository's log folder is known, so the shell costs every page little."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from repocop.config import Settings
from repocop.services import repositories, requirements, session_requests, sessions, tasks
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement, RequirementError
from repocop.services.session_requests import Standing
from repocop.services.sessions import Session, State
from repocop.services.tasks import Task

SEARCH_LIMIT = 8  # the matches of each kind a search returns


@dataclass(frozen=True)
class RequirementEntry:
    requirement: Requirement
    repository: str


@dataclass(frozen=True)
class SyncEntry:
    """A template sync, with the name of its repository."""

    task: Task
    repository: str


@dataclass(frozen=True)
class Matches:
    repositories: list[Repository]
    requirements: list[RequirementEntry]
    syncs: list[SyncEntry]

    def __bool__(self) -> bool:
        return bool(self.repositories or self.requirements or self.syncs)


@dataclass(frozen=True)
class SessionEntry:
    """A session, with the name of its repository."""

    session: Session
    repository: str


@dataclass(frozen=True)
class SessionList:
    """The sessions a page shows in one place, by its key: `r:<repository id>:<requirement>`
    for those working on a requirement, `p:<repository id>:<requirement>` for those with their
    requests, as a requirement's page shows them, `a:<repository id>` for all of a repository's,
    and `o:<repository id>` for those working on none of the requirements the page shows."""

    key: str
    sessions: tuple[Session, ...]


def sidebar(conn: sqlite3.Connection) -> list[Repository]:
    """The repositories, by name. No git, no files."""
    return repositories.list_all(conn)


def needs_input(conn: sqlite3.Connection, settings: Settings) -> list[SessionEntry]:
    """The sessions waiting for the developer, in every repository, the latest first."""
    return _needing_input(_sessions(conn, settings))


def session_lists(
    conn: sqlite3.Connection, settings: Settings, keys: list[str]
) -> tuple[list[SessionList], list[SessionEntry], dict[str, Standing]]:
    """The session lists named by `keys`, as they are now, the sessions that need input, and
    where the requests of the sessions in `p:` lists stand, by session. A key that names nothing
    known is left out."""
    found = _sessions(conn, settings)
    by_id = {repo.id: shown for repo, shown in found}
    shown_names: dict[int, set[str]] = {}
    parsed = []
    for key in dict.fromkeys(keys):
        kind, _, rest = key.partition(":")
        number, _, name = rest.partition(":")
        if not number.isdigit() or int(number) not in by_id or kind not in ("r", "p", "a", "o"):
            continue
        if kind in ("r", "p"):
            shown_names.setdefault(int(number), set()).add(name)
        parsed.append((key, kind, int(number), name))
    repos = {repo.id: repo for repo, _ in found}
    lists = []
    standings: dict[str, Standing] = {}
    for key, kind, repo_id, name in parsed:
        everyone = by_id[repo_id]
        if kind in ("r", "p"):
            picked = sessions.for_requirement(everyone, name)
        elif kind == "o":
            names = shown_names.get(repo_id, set())
            picked = tuple(s for s in everyone if s.requirement not in names)
        else:
            picked = tuple(everyone)
        lists.append(SessionList(key, picked))
        if kind == "p":
            for session in picked:
                standings[session.id] = session_requests.standing(repos[repo_id], settings, session)
    return lists, _needing_input(found), standings


def _sessions(
    conn: sqlite3.Connection, settings: Settings
) -> list[tuple[Repository, list[Session]]]:
    return [(repo, sessions.of(repo, settings)) for repo in repositories.list_all(conn)]


def _needing_input(found: list[tuple[Repository, list[Session]]]) -> list[SessionEntry]:
    entries = [
        SessionEntry(session, repo.name)
        for repo, shown in found
        for session in shown
        if session.state is State.NEEDS_INPUT
    ]
    return sorted(entries, key=lambda entry: entry.session.since, reverse=True)


def search(conn: sqlite3.Connection, settings: Settings, text: str) -> Matches:
    """What `text` finds, whatever its case: repositories and requirements by name, and template
    syncs by id, branch or workflow. Names that start with it come first.

    The requirements are those in each repository's requirements folder. A checkout that isn't
    there has none searched.
    """
    needle = text.strip().casefold()
    if not needle:
        return Matches([], [], [])
    listed = repositories.list_all(conn)
    found_requirements = [
        (requirement.name, RequirementEntry(requirement, repo.name))
        for repo in listed
        for requirement in _requirements(settings, repo)
    ]
    names = {repo.id: repo.name for repo in listed}
    return Matches(
        repositories=_best([(repo.name, repo) for repo in listed], needle),
        requirements=_best(found_requirements, needle),
        syncs=[
            SyncEntry(task, names.get(task.repository_id, ""))
            for task in tasks.search(conn, text, SEARCH_LIMIT)
        ],
    )


def _requirements(settings: Settings, repository: Repository) -> list[Requirement]:
    try:
        return requirements.in_folder(settings, repository)
    except RequirementError:  # the checkout isn't there: its folder can't be read
        return []


def _best[T](candidates: list[tuple[str, T]], needle: str) -> list[T]:
    """Of (name, item) candidates, the items whose name holds `needle`: names that start with it
    first, then by name, at most SEARCH_LIMIT."""
    found = [(name.casefold(), item) for name, item in candidates if needle in name.casefold()]
    found.sort(key=lambda match: (not match[0].startswith(needle), match[0]))
    return [item for _, item in found[:SEARCH_LIMIT]]
