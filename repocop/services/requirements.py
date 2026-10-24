"""Requirements: Markdown files in a repository's primary checkout, named by their files.

Every Markdown file in the `todo/` folder of the repository's `changes_dir` (default
`specs/changes`) is a requirement, whoever wrote it. Its file name, without `.md`, is its name,
and it has no id. The file is its text, with no title heading. The database records a
requirement only when something needs a row for it: its creation here, a kind saved for it, or
its first task. A row holds a key of the database's own, the path and the kind (invariant 4).
Saving writes that one file and commits it alone on the current branch, refused mid-merge,
mid-rebase or on a detached HEAD (ADR-004). Details: "Requirement storage" in
`specs/architecture.md`.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, repositories
from repocop.services.repositories import Repository, RepositoryError

logger = logging.getLogger(__name__)

SLUG_MAX_LENGTH = 50
NAME_MAX_LENGTH = 200
TODO_FOLDER = "todo"  # in a repository's changes folder: the requirements still to deliver
ARCHIVE_FOLDER = "archive"  # beside it: the delivered ones
# Before an archived change's name: the UTC date and time it was archived (ADR-028).
ARCHIVE_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z-")

# Requirement writes and commits run one at a time, so two can't take one file name and git
# never races on a checkout's index. RepoCop is one process.
_WRITE_LOCK = threading.Lock()


class RequirementError(RepoCopError):
    """A requirement can't be created, read, saved or committed as asked."""


class Kind(StrEnum):
    FEATURE = "feature"
    FIX = "fix"


class Location(StrEnum):
    ACTIVE = "active"  # at its path
    ARCHIVED = "archived"  # moved to the archive folder beside its folder
    MISSING = "missing"  # in neither place


@dataclass(frozen=True)
class Requirement:
    repository_id: int
    path: str  # relative to the checkout
    kind: Kind = Kind.FEATURE
    id: int | None = None  # the key of its database row; None until something records it

    @property
    def name(self) -> str:
        """Its file name without `.md`, which is what it's called: `bulk-import`."""
        return PurePosixPath(self.path).stem

    @property
    def file_name(self) -> str:
        return PurePosixPath(self.path).name

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Requirement:
        return cls(row["repository_id"], row["path"], Kind(row["kind"]), row["id"])


@dataclass(frozen=True)
class Content:
    body: str  # the file's whole text
    version: str  # a hash of the file, to notice edits made elsewhere before overwriting


@dataclass(frozen=True)
class Saved:
    requirement: Requirement
    committed: bool  # False when the commit failed; the file is saved either way


@dataclass(frozen=True)
class Detail:
    requirement: Requirement
    location: Location
    content: Content | None  # None when the file is missing
    uncommitted: bool


def slugify(name: str) -> str:
    """Lowercase letters, digits and single dashes, at most 50 characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].rstrip("-")


def create(
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    *,
    name: str,
    body: str,
    kind: str,
) -> Saved:
    """Write a new requirement as `<slug of name>.md` in the requirements folder, record it with
    its kind, and commit it alone. `name` makes its file name, and isn't written into the file.

    Refused when that file name is already used: in the requirements folder, in the archive
    beside it, or by a requirement RepoCop has recorded, whose branch may still exist.
    """
    name = _checked_name(name)
    body, checked_kind = _checked(body, kind)
    slug = slugify(name)
    if not slug:
        raise RequirementError("the name needs some letters or digits")
    checkout = _checkout(repository, settings)
    path = str(PurePosixPath(todo_dir(repository)) / f"{slug}.md")
    taken = RequirementError(
        f"{slug} is already the name of a requirement in {repository.name}, "
        "in its requirements folder, its archive or its history. Pick another name."
    )
    with _WRITE_LOCK:
        _check_committable(checkout)
        target = _inside(checkout, path)
        if (
            target.exists()
            or archived_path(checkout, path) is not None
            or _recorded(conn, repository, path) is not None
        ):
            raise taken
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8", newline="\n") as out:
                out.write(_text(body))
        except FileExistsError:
            raise taken from None
        requirement = record(conn, Requirement(repository.id, path, checked_kind))
        message = f"Add {requirement.name}"
        committed = _attempt(lambda: git.commit_file(checkout, path, message), path)
    return Saved(requirement, committed)


def update(
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    requirement: Requirement,
    *,
    body: str,
    kind: str,
    version: str,
) -> Saved:
    """Save new text and kind. Refused if the file changed since `version` was read. A new kind
    records a requirement that isn't recorded yet."""
    body, checked_kind = _checked(body, kind)
    checkout = _checkout(repository, settings)
    with _WRITE_LOCK:
        target = _inside(checkout, requirement.path)
        if not target.is_file():
            raise RequirementError(
                f"{requirement.path} isn't at its path any more (archived or moved), "
                "so it can't be edited here"
            )
        current = target.read_bytes()
        if _version(current) != version:
            raise RequirementError(
                f"{requirement.path} changed on disk since you opened it. Reload to see the "
                "current text; your edits weren't saved."
            )
        text = _text(body)
        rewrite = text.encode("utf-8") != current
        if rewrite:
            _check_committable(checkout)
        if rewrite or checked_kind is not requirement.kind:
            requirement = _set_kind(conn, requirement, checked_kind)
        if not rewrite:
            return Saved(requirement, not git.has_changes(checkout, requirement.path))
        target.write_text(text, encoding="utf-8", newline="\n")
        message = f"Update {requirement.name}"
        committed = _attempt(
            lambda: git.commit_file(checkout, requirement.path, message), requirement.path
        )
    return Saved(requirement, committed)


def commit(settings: Settings, repository: Repository, requirement: Requirement) -> None:
    """Commit the requirement's file alone, e.g. after a hand edit or a failed commit."""
    checkout = _checkout(repository, settings)
    with _WRITE_LOCK:
        target = _inside(checkout, requirement.path)
        if not target.is_file():
            raise RequirementError(f"{requirement.path} isn't at its path any more")
        if not git.has_changes(checkout, requirement.path):
            raise RequirementError(f"{requirement.path} has nothing to commit")
        _check_committable(checkout)
        git.commit_file(checkout, requirement.path, f"Update {requirement.name}")


def read(settings: Settings, repository: Repository, requirement: Requirement) -> Content:
    """The requirement's text and version, from its path or the archive folder. Refused when the
    file can't be read, or isn't UTF-8 text."""
    checkout = _checkout(repository, settings)
    for path in (requirement.path, archived_path(checkout, requirement.path)):
        if path is None:
            continue
        target = _inside(checkout, path)
        if target.is_file():
            try:
                data = target.read_bytes()
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise RequirementError(f"{path} can't be read: it isn't UTF-8 text") from None
            except OSError as exc:
                raise RequirementError(f"{path} can't be read: {exc.strerror}") from None
            return Content(text.strip("\n"), _version(data))
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


def in_folder(
    conn: sqlite3.Connection, settings: Settings, repository: Repository
) -> list[Requirement]:
    """Every Markdown file in the repository's requirements folder, by file name, as a
    requirement: as recorded, or not recorded yet. A link is listed without being read."""
    checkout = _checkout(repository, settings)
    folder = PurePosixPath(todo_dir(repository))
    recorded = {requirement.path: requirement for requirement in list_for(conn, repository)}
    found = []
    for entry in _markdown_files(checkout, folder):
        path = str(folder / entry.name)
        found.append(recorded.get(path) or Requirement(repository.id, path))
    return found


def find(
    conn: sqlite3.Connection, settings: Settings, repository: Repository, file_name: str
) -> Requirement | None:
    """The requirement whose file is `file_name` in the repository's requirements folder, or was
    before it was archived, whether recorded or not. None for any other name."""
    stem = file_name.removesuffix(".md")
    if not stem or stem == file_name or PurePosixPath(file_name).name != file_name:
        return None
    if stem in (".", "..") or "\\" in file_name:
        return None
    path = str(PurePosixPath(todo_dir(repository)) / file_name)
    if (recorded := _recorded(conn, repository, path)) is not None:
        return recorded
    try:
        checkout = _checkout(repository, settings)
        entry = _inside(checkout, todo_dir(repository)) / file_name
        if entry.is_file() or entry.is_symlink() or archived_path(checkout, path) is not None:
            return Requirement(repository.id, path)
    except RequirementError:
        pass  # a missing checkout, or a folder that leads outside it, holds no requirements
    return None


def record(conn: sqlite3.Connection, requirement: Requirement) -> Requirement:
    """The requirement as the database records it, recording it with its kind first if it
    isn't yet."""
    if requirement.id is not None:
        return requirement
    now = db.timestamp()
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO requirements (repository_id, path, kind, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT (repository_id, path) DO NOTHING",
            (requirement.repository_id, requirement.path, requirement.kind.value, now, now),
        )
        row = conn.execute(
            "SELECT * FROM requirements WHERE repository_id = ? AND path = ?",
            (requirement.repository_id, requirement.path),
        ).fetchone()
    return Requirement.from_row(row)


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


def detail(settings: Settings, repository: Repository, requirement: Requirement) -> Detail:
    """Where the requirement's file is, what it says, and whether it has uncommitted changes."""
    where = location(settings, repository, requirement)
    content = None if where is Location.MISSING else read(settings, repository, requirement)
    uncommitted = where is Location.ACTIVE and is_uncommitted(settings, repository, requirement)
    return Detail(requirement, where, content, uncommitted)


def details_for(
    conn: sqlite3.Connection, settings: Settings, repository: Repository
) -> list[Detail]:
    return [detail(settings, repository, r) for r in list_for(conn, repository)]


def get(conn: sqlite3.Connection, requirement_id: int) -> Requirement | None:
    row = conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone()
    return Requirement.from_row(row) if row else None


def list_for(conn: sqlite3.Connection, repository: Repository) -> list[Requirement]:
    rows = conn.execute(
        "SELECT * FROM requirements WHERE repository_id = ? ORDER BY id", (repository.id,)
    )
    return [Requirement.from_row(row) for row in rows]


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


def _text(body: str) -> str:
    """What a requirement's file holds for `body`: the text, ending in one newline."""
    text = body.strip("\n")
    return f"{text}\n" if text else ""


def _checked_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise RequirementError("give the requirement a name")
    if "\n" in name or "\r" in name:
        raise RequirementError("the name must be a single line")
    if len(name) > NAME_MAX_LENGTH:
        raise RequirementError(f"keep the name under {NAME_MAX_LENGTH} characters")
    return name


def _checked(body: str, kind: str) -> tuple[str, Kind]:
    try:
        checked_kind = Kind(kind)
    except ValueError:
        raise RequirementError(f"unknown kind {kind!r}: use feature or fix") from None
    return body.replace("\r\n", "\n").replace("\r", "\n"), checked_kind


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


def _check_committable(checkout: Path) -> None:
    """Refuse to commit in a checkout mid-merge, mid-rebase or on a detached HEAD (ADR-004)."""
    if operation := git.unfinished_operation(checkout):
        raise RequirementError(
            f"{checkout} is in the middle of a {operation}. Finish or abort it, then try again."
        )
    if git.current_branch(checkout) is None:
        raise RequirementError(
            f"{checkout} is on a detached HEAD. Check out a branch, then try again."
        )


def _attempt(commit: Callable[[], None], path: str) -> bool:
    """Run a commit; on failure keep the saved file, log why, and report False."""
    try:
        commit()
    except git.GitError as exc:
        logger.warning("Saved %s but couldn't commit it: %s", path, exc)
        return False
    return True


def _recorded(conn: sqlite3.Connection, repository: Repository, path: str) -> Requirement | None:
    row = conn.execute(
        "SELECT * FROM requirements WHERE repository_id = ? AND path = ?", (repository.id, path)
    ).fetchone()
    return Requirement.from_row(row) if row else None


def _set_kind(conn: sqlite3.Connection, requirement: Requirement, kind: Kind) -> Requirement:
    """The requirement with `kind`, as recorded: a new kind records one that isn't yet."""
    if requirement.id is None:
        return (
            requirement
            if kind is requirement.kind
            else record(conn, replace(requirement, kind=kind))
        )
    with db.transaction(conn):
        conn.execute(
            "UPDATE requirements SET kind = ?, updated_at = ? WHERE id = ?",
            (kind.value, db.timestamp(), requirement.id),
        )
    return replace(requirement, kind=kind)


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


def _version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
