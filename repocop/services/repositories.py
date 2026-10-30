"""Repository registry: register repos by remote URL or by an existing checkout's name, clone or
find their checkouts, list them.

A repository named `<name>` has its human-owned primary checkout at `<repos_root>/<name>` and
its RepoCop-owned worktrees under `<worktrees_root>/<name>/` (ADR-015).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import bootstrap, git

NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")

# RepoCop is one process, so this serializes every registration (see `register`).
_REGISTER_LOCK = threading.Lock()
logger = logging.getLogger(__name__)
FETCHES_AT_ONCE = 8  # how many repositories fetch side by side


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


@dataclass(frozen=True)
class Remote:
    url: str

    @property
    def web_url(self) -> str | None:
        """The repository's page on the remote's host, or None when the remote isn't on one."""
        return git.web_url(self.url)


@dataclass(frozen=True)
class Registration:
    repository: Repository
    outcome: Outcome


@dataclass(frozen=True)
class Candidate:
    """A repository about to be registered, whose default branch is still to be chosen."""

    remote_url: str
    name: str
    primary_path: Path
    outcome: Outcome  # what registering it does: clone it, or register the checkout found
    branches: git.RemoteBranches  # what to choose from, and the default origin names
    unreachable: str | None = None  # why origin couldn't be asked: branches as last fetched


@dataclass(frozen=True)
class _Target:
    url: str
    name: str
    primary_path: Path
    worktrees_root: Path
    outcome: Outcome


def propose(
    conn: sqlite3.Connection, settings: Settings, remote_url: str, name: str = ""
) -> Candidate | Registration:
    """What registering would do, with `origin`'s branches to choose the default branch from and
    the one `origin` itself names, asked of `origin`. Nothing is cloned or recorded.

    For a checkout already on disk whose `origin` can't be reached, its branches are as it last
    fetched them. A remote that is already registered returns the existing repository.
    """
    target = _target(conn, settings, remote_url, name)
    if isinstance(target, Registration):
        return target
    if target.outcome is Outcome.CLONED:
        settings.repos_root.mkdir(parents=True, exist_ok=True)
        try:
            branches = git.remote_branches(target.url, cwd=settings.repos_root)
        except git.GitError as exc:
            raise RepositoryError(f"{target.url} can't be reached: {exc}") from exc
        return Candidate(target.url, target.name, target.primary_path, target.outcome, branches)
    try:
        branches = git.remote_branches("origin", cwd=target.primary_path)
    except git.GitError as exc:
        found = git.tracked_branches(target.primary_path)
        return Candidate(
            target.url, target.name, target.primary_path, target.outcome, found, str(exc)
        )
    return Candidate(target.url, target.name, target.primary_path, target.outcome, branches)


def register(
    conn: sqlite3.Connection,
    settings: Settings,
    remote_url: str,
    name: str = "",
    *,
    default_branch: str,
) -> Registration:
    """Register the repo at `remote_url`, cloning it unless a checkout of it is already on disk,
    with `default_branch` as the branch it compares with, which its user chose.

    With no `remote_url`, the checkout already at `<repos_root>/<name>` is registered, with its
    `origin` as the remote. A remote that is already registered, under any spelling, returns the
    existing repository.
    An existing directory that isn't a checkout of this remote is refused and left untouched, and
    so is a default branch git wouldn't take as a branch's name.
    Registrations run one at a time, so concurrent adds of one remote register it once.
    """
    with _REGISTER_LOCK:
        return _register(conn, settings, remote_url, name, default_branch.strip())


def set_default_branch(
    conn: sqlite3.Connection, settings: Settings, repository: Repository, branch: str
) -> Repository:
    """Make `branch` the repository's default branch. Refused unless `origin` has it, as the
    checkout last fetched."""
    if branch not in origin_branches(repository, settings).branches:
        raise RepositoryError(f"origin has no branch {branch}, as last fetched")
    with db.transaction(conn):
        row = conn.execute(
            "UPDATE repositories SET default_branch = ?, updated_at = ? WHERE id = ? RETURNING *",
            (branch, db.timestamp(), repository.id),
        ).fetchone()
    return Repository.from_row(row)


def _target(
    conn: sqlite3.Connection, settings: Settings, remote_url: str, name: str
) -> _Target | Registration:
    """Where registering `remote_url` or the checkout called `name` puts it, and whether it
    clones, refused when that can't be done safely. A registered remote returns its record."""
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
    if not primary_path.exists():
        return _Target(url, name, primary_path, worktrees_root, Outcome.CLONED)
    origin = git.remote_url(primary_path) if git.is_checkout(primary_path) else None
    if origin is None or git.remote_identity(origin) != identity:
        raise RepositoryError(
            f"{primary_path} already exists and is not a checkout of {url}, so it was left "
            "untouched. Choose another name."
        )
    return _Target(url, name, primary_path, worktrees_root, Outcome.FOUND_ON_DISK)


def _register(
    conn: sqlite3.Connection, settings: Settings, remote_url: str, name: str, default_branch: str
) -> Registration:
    target = _target(conn, settings, remote_url, name)
    if isinstance(target, Registration):
        return target
    settings.repos_root.mkdir(parents=True, exist_ok=True)
    if not git.is_branch_name(default_branch, cwd=settings.repos_root):
        raise RepositoryError(f"{default_branch} isn't a name git takes for a branch")
    if target.outcome is Outcome.CLONED:
        git.clone(target.url, target.primary_path)

    now = db.timestamp()
    try:
        with db.transaction(conn):
            row = conn.execute(
                "INSERT INTO repositories (name, remote_url, primary_path, worktrees_root,"
                " default_branch, changes_dir, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
                (
                    target.name,
                    target.url,
                    str(target.primary_path),
                    str(target.worktrees_root),
                    default_branch,
                    settings.changes_dir,
                    now,
                    now,
                ),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise RepositoryError(f"{target.name!r} was registered at the same time: {exc}") from exc
    return Registration(Repository.from_row(row), target.outcome)


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
    if not checkout_present(repository, settings):
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


def origin_branches(repository: Repository, settings: Settings) -> git.RemoteBranches:
    """`origin`'s branches and default branch as the primary checkout last fetched them."""
    return git.tracked_branches(require_checkout(repository, settings))


def checkout_state(repository: Repository, settings: Settings) -> git.CheckoutState:
    """The primary checkout's branch, upstream and uncommitted files, read from git now."""
    return git.checkout_state(require_checkout(repository, settings))


def last_fetch(repository: Repository, settings: Settings) -> datetime | None:
    """When the primary checkout last fetched, or None if it never has."""
    return git.last_fetch(require_checkout(repository, settings))


def fetch(repository: Repository, settings: Settings) -> str | None:
    """Fetch `origin` in the primary checkout: only remote-tracking branches change (ADR-022).
    Returns the default branch `origin` names now, asked of it, or None when it names none or
    can't say. The repository's own default branch is left as its user chose it."""
    checkout = require_checkout(repository, settings)
    git.fetch(checkout)
    try:
        return git.remote_branches("origin", cwd=checkout).default
    except git.GitError as exc:
        logger.warning(
            "Fetched %s, but couldn't ask origin for its default branch: %s", repository.name, exc
        )
        return None


@dataclass(frozen=True)
class Fetched:
    """How one repository's fetch went."""

    error: str | None  # why it failed, or None when it fetched
    origin_default: str | None = None  # the default branch origin names now, as `fetch` says


def fetch_each(listed: list[Repository], settings: Settings) -> dict[int, Fetched]:
    """Fetch each repository as `fetch` does, side by side, each with its own timeout. Returns
    how each went, by its id: one failing doesn't stop the others."""

    def attempt(repository: Repository) -> Fetched:
        try:
            return Fetched(None, fetch(repository, settings))
        except RepoCopError as exc:
            return Fetched(str(exc))

    with ThreadPoolExecutor(max_workers=max(1, min(FETCHES_AT_ONCE, len(listed)))) as pool:
        results = {repository.id: pool.submit(attempt, repository) for repository in listed}
    return {repository_id: done.result() for repository_id, done in results.items()}


def require_checkout(repository: Repository, settings: Settings) -> Path:
    """The primary checkout's path, refused unless it still holds this repository (see status)."""
    if not checkout_present(repository, settings):
        raise RepositoryError(
            f"the checkout at {repository.primary_path} isn't there, no longer resolves inside "
            f"{settings.repos_root}, or isn't a checkout of {repository.remote_url}"
        )
    return repository.primary_path


def remote(repository: Repository, settings: Settings) -> Remote:
    """The repository's remote as its checkout's `origin` has it now, read from git, so another
    spelling of it set since it was registered, such as ssh for https, shows as it is. While the
    checkout isn't there (see status), the remote it was registered with."""
    return Remote(_present_origin(repository, settings) or repository.remote_url)


def checkout_present(repository: Repository, settings: Settings) -> bool:
    """Whether the repository's checkout is there: its status isn't `missing`."""
    return _present_origin(repository, settings) is not None


def _present_origin(repository: Repository, settings: Settings) -> str | None:
    """The checkout's `origin` when the recorded path is a real folder in `repos_root` holding a
    checkout of this remote, else None."""
    path = repository.primary_path
    if path.is_symlink() or not _is_child(settings.repos_root, path) or not git.is_checkout(path):
        return None
    origin = git.remote_url(path)
    identity = git.remote_identity(repository.remote_url)
    return origin if origin is not None and git.remote_identity(origin) == identity else None


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
