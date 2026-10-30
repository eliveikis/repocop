"""Requirements: Markdown files in a repository's primary checkout, named by their files.

Every Markdown file in the `todo/` folder of the repository's `changes_dir` (default
`specs/changes`) is a requirement. Its developer writes and commits it in their own editor, and
RepoCop only reads it. Its file name, without `.md`, is its name, and it has no id. The file is
its text, with no title heading. The database holds nothing of it (invariant 4). Details:
"Requirement storage" in `specs/architecture.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, repositories
from repocop.services.repositories import Repository, RepositoryError

TODO_FOLDER = "todo"  # in a repository's changes folder: the requirements still to deliver
ARCHIVE_FOLDER = "archive"  # beside it: the delivered ones
# Before an archived change's name: the UTC date and time it was archived (ADR-028).
ARCHIVE_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z-")


class RequirementError(RepoCopError):
    """A requirement can't be found or read as asked."""


class Location(StrEnum):
    ACTIVE = "active"  # at its path
    ARCHIVED = "archived"  # moved to the archive folder beside its folder
    MISSING = "missing"  # in neither place


@dataclass(frozen=True)
class Requirement:
    repository_id: int
    path: str  # relative to the checkout

    @property
    def name(self) -> str:
        """Its file name without `.md`, which is what it's called: `bulk-import`."""
        return PurePosixPath(self.path).stem

    @property
    def file_name(self) -> str:
        return PurePosixPath(self.path).name


@dataclass(frozen=True)
class Content:
    body: str  # the file's whole text
    path: str  # where the file was read, relative to the checkout: its path or the archive's


@dataclass(frozen=True)
class Detail:
    requirement: Requirement
    location: Location
    content: Content | None  # None when the file is missing
    uncommitted: bool


def read(settings: Settings, repository: Repository, requirement: Requirement) -> Content:
    """The requirement's text, from its path or the archive folder. Refused when the file can't
    be read, or isn't UTF-8 text."""
    checkout = _checkout(repository, settings)
    for path in (requirement.path, archived_path(checkout, requirement.path)):
        if path is None:
            continue
        target = _inside(checkout, path)
        if target.is_file():
            try:
                text = target.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise RequirementError(f"{path} can't be read: it isn't UTF-8 text") from None
            except OSError as exc:
                raise RequirementError(f"{path} can't be read: {exc.strerror}") from None
            return Content(text.strip("\n"), path)
    raise RequirementError(f"{requirement.path} is missing from {checkout}")


def location(settings: Settings, repository: Repository, requirement: Requirement) -> Location:
    checkout = _checkout(repository, settings)
    if _inside(checkout, requirement.path).is_file():
        return Location.ACTIVE
    if archived_path(checkout, requirement.path) is not None:
        return Location.ARCHIVED
    return Location.MISSING


def is_uncommitted(settings: Settings, repository: Repository, requirement: Requirement) -> bool:
    """True if the file at the requirement's path is untracked, modified or staged."""
    checkout = _checkout(repository, settings)
    _inside(checkout, requirement.path)
    return git.has_changes(checkout, requirement.path)


def todo_dir(repository: Repository) -> str:
    """The folder of the repository's requirements still to deliver, relative to its checkout."""
    return str(PurePosixPath(repository.changes_dir) / TODO_FOLDER)


def archive_dir(repository: Repository) -> str:
    """The folder of the repository's delivered requirements, relative to its checkout."""
    return str(PurePosixPath(repository.changes_dir) / ARCHIVE_FOLDER)


def in_folder(settings: Settings, repository: Repository) -> list[Requirement]:
    """Every Markdown file in the repository's requirements folder, by file name, as a
    requirement. A link is listed without being read."""
    checkout = _checkout(repository, settings)
    folder = PurePosixPath(todo_dir(repository))
    return [
        Requirement(repository.id, str(folder / entry.name))
        for entry in _markdown_files(checkout, folder)
    ]


def find(settings: Settings, repository: Repository, file_name: str) -> Requirement | None:
    """The requirement whose file is `file_name` in the repository's requirements folder, or was
    before it was archived. None for any other name."""
    stem = file_name.removesuffix(".md")
    if not stem or stem == file_name or PurePosixPath(file_name).name != file_name:
        return None
    if stem in (".", "..") or "\\" in file_name:
        return None
    path = str(PurePosixPath(todo_dir(repository)) / file_name)
    try:
        checkout = _checkout(repository, settings)
        entry = _inside(checkout, todo_dir(repository)) / file_name
        if entry.is_file() or entry.is_symlink() or archived_path(checkout, path) is not None:
            return Requirement(repository.id, path)
    except RequirementError:
        pass  # a missing checkout, or a folder that leads outside it, holds no requirements
    return None


def change_files(
    settings: Settings, repository: Repository
) -> tuple[dict[str, str | None], list[str]]:
    """The text of each Markdown file in the repository's requirements folder, by file name, and
    the file names in the archive beside it. A file that links outside the checkout, or can't be
    read, has None for its text, and an archived one that links outside it isn't listed."""
    checkout = _checkout(repository, settings)
    folder = PurePosixPath(todo_dir(repository))
    texts: dict[str, str | None] = {}
    for entry in _markdown_files(checkout, folder):
        texts[entry.name] = _text_of(checkout, entry)
    archived = [
        entry.name
        for entry in _markdown_files(checkout, folder.parent / ARCHIVE_FOLDER)
        if entry.resolve().is_relative_to(checkout.resolve())
    ]
    return texts, archived


def files_on_disk(repository: Repository) -> tuple[list[str], list[str]]:
    """The Markdown file names in the repository's requirements folder, and in the archive beside
    it, read from disk alone, without git: none for a folder that isn't there or that leads
    outside the checkout."""
    found: list[list[str]] = []
    for folder in (todo_dir(repository), archive_dir(repository)):
        try:
            entries = _markdown_files(repository.primary_path, PurePosixPath(folder))
        except (RequirementError, OSError):
            entries = []
        found.append([entry.name for entry in entries])
    return found[0], found[1]


def detail(settings: Settings, repository: Repository, requirement: Requirement) -> Detail:
    """Where the requirement's file is, what it says, and whether it has uncommitted changes."""
    where = location(settings, repository, requirement)
    content = None if where is Location.MISSING else read(settings, repository, requirement)
    uncommitted = where is Location.ACTIVE and is_uncommitted(settings, repository, requirement)
    return Detail(requirement, where, content, uncommitted)


def archived_path(checkout: Path, path: str) -> str | None:
    """Where the requirement once at `path` is in the archive folder beside its folder, if it is.

    `/complete-change` stamps an archived file's name with when it was archived; an older
    archive may have kept the name as it was. Of several, the latest stamp wins.
    """
    relative = PurePosixPath(path)
    folder = relative.parent.parent / ARCHIVE_FOLDER
    directory = _inside(checkout, str(folder))
    if not directory.is_dir():
        return None
    name = relative.name
    found = [
        entry.name
        for entry in directory.iterdir()
        if entry.is_file()
        and _archived_name(entry.name) == name
        and entry.resolve().is_relative_to(checkout.resolve())
    ]
    if not found:
        return None
    return str(folder / max(found, key=lambda found_name: (found_name != name, found_name)))


def _checkout(repository: Repository, settings: Settings) -> Path:
    try:
        return repositories.require_checkout(repository, settings)
    except RepositoryError as exc:
        raise RequirementError(str(exc)) from exc


def _inside(checkout: Path, path: str) -> Path:
    """`checkout/path`, refused if it resolves outside the checkout (e.g. through a symlink)."""
    target = checkout / path
    if not target.resolve().is_relative_to(checkout.resolve()):
        raise RequirementError(f"{path} resolves outside {checkout}")
    return target


def _markdown_files(checkout: Path, folder: PurePosixPath) -> list[Path]:
    """The Markdown files in `folder` of the checkout, none if it isn't there."""
    directory = _inside(checkout, str(folder))
    if not directory.is_dir():
        return []
    return sorted(e for e in directory.iterdir() if e.is_file() and e.suffix == ".md")


def _text_of(checkout: Path, file: Path) -> str | None:
    """A file's text, or None when it links outside the checkout or can't be read."""
    if not file.resolve().is_relative_to(checkout.resolve()):
        return None
    try:
        return file.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def _archived_name(file_name: str) -> str:
    """A file's name without the stamp an archive puts before it, if it has one."""
    stamp = ARCHIVE_STAMP.match(file_name)
    return file_name[stamp.end() :] if stamp else file_name
