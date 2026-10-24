"""What the navigation every page shares shows: the registered repositories and the tasks active
across them, read from the database alone, and the repositories, requirements and tasks that a
search finds."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from repocop.config import Settings
from repocop.services import repositories, requirements, tasks, worktrees
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement, RequirementError
from repocop.services.tasks import Task

SEARCH_LIMIT = 8  # the matches of each kind a search returns


@dataclass(frozen=True)
class TaskEntry:
    """A task, with the names of its repository and of its requirement, if it has one."""

    task: Task
    repository: str
    requirement: str | None


@dataclass(frozen=True)
class RequirementEntry:
    requirement: Requirement
    repository: str


@dataclass(frozen=True)
class Sidebar:
    repositories: list[Repository]
    active_tasks: list[TaskEntry]


@dataclass(frozen=True)
class Matches:
    repositories: list[Repository]
    requirements: list[RequirementEntry]
    tasks: list[TaskEntry]

    def __bool__(self) -> bool:
        return bool(self.repositories or self.requirements or self.tasks)


def sidebar(conn: sqlite3.Connection) -> Sidebar:
    """The repositories, by name, and the active tasks, newest first. No git, no files."""
    listed = repositories.list_all(conn)
    return Sidebar(listed, _entries(conn, tasks.list_active(conn), listed))


def active_tasks(conn: sqlite3.Connection) -> list[TaskEntry]:
    """The active tasks in every repository, newest first. No git, no files."""
    return _entries(conn, tasks.list_active(conn), repositories.list_all(conn))


def search(conn: sqlite3.Connection, settings: Settings, text: str) -> Matches:
    """What `text` finds, whatever its case: repositories by name, requirements by name or
    branch, and tasks by id, branch or workflow. Names that start with it come first.

    The requirements are those in each repository's requirements folder and those recorded. A
    checkout that isn't there has only its recorded ones searched.
    """
    needle = text.strip().casefold()
    if not needle:
        return Matches([], [], [])
    listed = repositories.list_all(conn)
    found_requirements = [
        (
            requirement.name,
            _requirement_terms(requirement),
            RequirementEntry(requirement, repo.name),
        )
        for repo in listed
        for requirement in _requirements(conn, settings, repo)
    ]
    return Matches(
        repositories=_best([(repo.name, repo.name, repo) for repo in listed], needle),
        requirements=_best(found_requirements, needle),
        tasks=_entries(conn, tasks.search(conn, text, SEARCH_LIMIT), listed),
    )


def _requirements(
    conn: sqlite3.Connection, settings: Settings, repository: Repository
) -> list[Requirement]:
    """The repository's requirements: those in its folder, then those only recorded, such as
    archived ones."""
    try:
        found = requirements.in_folder(conn, settings, repository)
    except RequirementError:  # the checkout isn't there: its folder can't be read
        found = []
    paths = {requirement.path for requirement in found}
    return found + [r for r in requirements.list_for(conn, repository) if r.path not in paths]


def _requirement_terms(requirement: Requirement) -> str:
    """What a search matches a requirement on: its name and the branch it is worked on."""
    _, branch = worktrees.requirement_names(requirement.name)
    return f"{requirement.name}\n{branch}"


def _best[T](candidates: list[tuple[str, str, T]], needle: str) -> list[T]:
    """Of (name, terms, item) candidates, the items whose terms hold `needle`: names that start
    with it first, then by name, at most SEARCH_LIMIT."""
    found = [
        (name.casefold(), item) for name, terms, item in candidates if needle in terms.casefold()
    ]
    found.sort(key=lambda match: (not match[0].startswith(needle), match[0]))
    return [item for _, item in found[:SEARCH_LIMIT]]


def _entries(
    conn: sqlite3.Connection, found: list[Task], listed: list[Repository]
) -> list[TaskEntry]:
    names = {repo.id: repo.name for repo in listed}
    entries = []
    for task in found:
        requirement = requirements.get(conn, task.requirement_id) if task.requirement_id else None
        entries.append(
            TaskEntry(
                task, names.get(task.repository_id, ""), requirement.name if requirement else None
            )
        )
    return entries
