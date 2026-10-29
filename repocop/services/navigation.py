"""What the navigation every page shares shows: the registered repositories, read from the
database alone, and the repositories, requirements and template syncs that a search finds."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from repocop.config import Settings
from repocop.services import repositories, requirements, tasks
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement, RequirementError
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


def sidebar(conn: sqlite3.Connection) -> list[Repository]:
    """The repositories, by name. No git, no files."""
    return repositories.list_all(conn)


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
