"""Repository registry: register repos by remote URL or by an existing checkout's name, clone or
find their checkouts, list them.

A repository named `<name>` has its human-owned primary checkout at `<repos_root>/<name>` and
its RepoCop-owned worktrees under `<worktrees_root>/<name>/` (ADR-015).
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import bootstrap, git

NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")

# RepoCop is one process, so this serializes every registration (see `register`).
_REGISTER_LOCK = threading.Lock()


class RepositoryError(RepoCopError):
    """A repository can't be registered as asked."""


class Status(StrEnum):
    READY = "ready"
    BEHIND = "behind"  # behind the template
    NO_COMMITS = "no_commits"
    MISSING = "missing"


class Outcome(StrEnum):
    CLONED = "cloned"
    FOUND_ON_DISK = "found_on_disk"
    ALREADY_REGISTERED = "already_registered"


@dataclass(frozen=True)
class Repository:
    id: int
    name: str
    remote_url: str
    primary_path: Path
    worktrees_root: Path
    default_branch: str
    changes_dir: str  # holds its todo/ and archive/ folders, relative to its checkout
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Repository:
        return cls(
            id=row["id"],
            name=row["name"],
            remote_url=row["remote_url"],
            primary_path=Path(row["primary_path"]),
            worktrees_root=Path(row["worktrees_root"]),
            default_branch=row["default_branch"],
            changes_dir=row["changes_dir"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @property
    def web_url(self) -> str | None:
        """The repository's page on its remote's host, or None when the remote isn't on one."""
        return git.web_url(self.remote_url)


@dataclass(frozen=True)
class Registration:
    repository: Repository
    outcome: Outcome


def register(
    conn: sqlite3.Connection, settings: Settings, remote_url: str, name: str = ""
) -> Registration:
    """Register the repo at `remote_url`, cloning it unless a checkout of it is already on disk.

    With no `remote_url`, the checkout already at `<repos_root>/<name>` is registered, with its
    `origin` as the remote. A remote that is already registered, under any spelling, returns the
    existing repository.
    An existing directory that isn't a checkout of this remote is refused and left untouched.
    Registrations run one at a time, so concurrent adds of one remote register it once.
    """
    with _REGISTER_LOCK:
        return _register(conn, settings, remote_url, name)


def _register(
    conn: sqlite3.Connection, settings: Settings, remote_url: str, name: str
) -> Registration:
    remote_url, name = remote_url.strip(), name.strip()
    url = git.check_remote_url(remote_url or _origin_of_checkout(settings, name))
    identity = git.remote_identity(url)
    for existing in list_all(conn):
        if git.remote_identity(existing.remote_url) == identity:
            return Registration(existing, Outcome.ALREADY_REGISTERED)

    name = name or _name_from_url(url)
    _check_name(name)
    if conn.execute("SELECT 1 FROM repositories WHERE name = ?", (name,)).fetchone():
        raise RepositoryError(f"the name {name!r} is already used by another repository")
    primary_path = _child(settings.repos_root, name)
    worktrees_root = _child(settings.worktrees_root, name)
    if primary_path.is_symlink():
        raise RepositoryError(
            f"{primary_path} is a symlink, so it was left untouched. Choose another name."
        )

    if primary_path.exists():
        origin = git.remote_url(primary_path) if git.is_checkout(primary_path) else None
        if origin is None or git.remote_identity(origin) != identity:
            raise RepositoryError(
                f"{primary_path} already exists and is not a checkout of {url}, so it was left "
                "untouched. Choose another name."
            )
        outcome = Outcome.FOUND_ON_DISK
    else:
        settings.repos_root.mkdir(parents=True, exist_ok=True)
        git.clone(url, primary_path)
        outcome = Outcome.CLONED

    now = db.timestamp()
    try:
        with db.transaction(conn):
            row = conn.execute(
                "INSERT INTO repositories (name, remote_url, primary_path, worktrees_root,"
                " default_branch, changes_dir, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
                (
                    name,
                    url,
                    str(primary_path),
                    str(worktrees_root),
                    git.default_branch(primary_path),
                    settings.changes_dir,
                    now,
                    now,
                ),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise RepositoryError(f"{name!r} was registered at the same time: {exc}") from exc
    return Registration(Repository.from_row(row), outcome)


def get(conn: sqlite3.Connection, repository_id: int) -> Repository | None:
    row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repository_id,)).fetchone()
    return Repository.from_row(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[Repository]:
    rows = conn.execute("SELECT * FROM repositories ORDER BY name")
    return [Repository.from_row(row) for row in rows]


def status(repository: Repository, settings: Settings) -> Status:
    """Whether the primary checkout is there, and its default branch on `origin` up to date with
    the repo template.

    Missing when the checkout isn't on disk, or its recorded path no longer resolves inside
    `repos_root` (after a config change or a symlink swap); git never runs there. No commits
    before the first commit. Behind when the default branch on `origin`, as last fetched, lacks
    a template file or is otherwise behind the template, or can't be compared with it, and ready
    otherwise.
    """
    if not _checkout_present(repository, settings):
        return Status.MISSING
    try:
        up_to_date = template_plan(repository, settings).up_to_date
    except bootstrap.NoCommitsError:
        return Status.NO_COMMITS
    except (bootstrap.BootstrapError, RepositoryError):
        return Status.BEHIND
    return Status.READY if up_to_date else Status.BEHIND


def origin_default(repository: Repository) -> str:
    """The repository's default branch on `origin`, as last fetched: `origin/<default branch>`."""
    return f"origin/{repository.default_branch}"


def template_plan(repository: Repository, settings: Settings) -> bootstrap.SyncPlan:
    """How each repo template file compares with the default branch on `origin`, as last
    fetched: where a merged pull request lands, whatever the checkout's own branch holds
    (ADR-006, ADR-029). The same comparison whether it is shown as a status or as a sync's plan.
    Refused, saying to fetch, when the checkout doesn't have that branch."""
    checkout = require_checkout(repository, settings)
    ref = origin_default(repository)
    try:
        return bootstrap.sync_plan(settings.template_dir, checkout, ref, repository.name)
    except bootstrap.NoCommitsError:
        raise
    except bootstrap.BootstrapError:
        try:
            git.resolve(checkout, ref)
        except git.GitError:
            raise RepositoryError(
                f"{ref} isn't in {repository.name}'s checkout. Fetch it first."
            ) from None
        raise


def checkout_state(repository: Repository, settings: Settings) -> git.CheckoutState:
    """The primary checkout's branch, upstream and uncommitted files, read from git now."""
    return git.checkout_state(require_checkout(repository, settings))


def fetch(repository: Repository, settings: Settings) -> None:
    """Fetch `origin` in the primary checkout: only remote-tracking branches change (ADR-022)."""
    git.fetch(require_checkout(repository, settings))


def require_checkout(repository: Repository, settings: Settings) -> Path:
    """The primary checkout's path, refused unless it still holds this repository (see status)."""
    if not _checkout_present(repository, settings):
        raise RepositoryError(
            f"the checkout at {repository.primary_path} isn't there, no longer resolves inside "
            f"{settings.repos_root}, or isn't a checkout of {repository.remote_url}"
        )
    return repository.primary_path


def _checkout_present(repository: Repository, settings: Settings) -> bool:
    """The recorded path is a real folder in `repos_root` holding a checkout of this remote."""
    path = repository.primary_path
    if path.is_symlink() or not _is_child(settings.repos_root, path) or not git.is_checkout(path):
        return False
    origin = git.remote_url(path)
    identity = git.remote_identity(repository.remote_url)
    return origin is not None and git.remote_identity(origin) == identity


def _origin_of_checkout(settings: Settings, name: str) -> str:
    """The `origin` URL of the checkout already at `<repos_root>/<name>`."""
    if not name:
        raise RepositoryError(
            f"give a remote URL, or the name of a checkout already in {settings.repos_root}"
        )
    _check_name(name)
    path = _child(settings.repos_root, name)
    if path.is_symlink():
        raise RepositoryError(f"{path} is a symlink, so it was left untouched")
    if not path.exists():
        raise RepositoryError(f"there's no {path}: give its remote URL to clone it")
    if not git.is_checkout(path):
        raise RepositoryError(f"{path} isn't a git checkout, so it was left untouched")
    origin = git.remote_url(path)
    if origin is None:
        raise RepositoryError(
            f"{path} has no origin remote, so there's no remote to register. Add one, or give "
            "the remote URL."
        )
    return origin


def _name_from_url(url: str) -> str:
    return re.split(r"[/:]", url.rstrip("/"))[-1].removesuffix(".git")


def _check_name(name: str) -> None:
    if not NAME_PATTERN.fullmatch(name):
        raise RepositoryError(
            f"invalid repository name {name!r}: use up to 100 letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )


def _child(root: Path, name: str) -> Path:
    """`root/name`, refused if it resolves outside `root` (e.g. through a symlink)."""
    path = root / name
    if not _is_child(root, path):
        raise RepositoryError(f"{path} resolves outside {root}")
    return path


def _is_child(root: Path, path: Path) -> bool:
    return path.resolve().parent == root.resolve()
