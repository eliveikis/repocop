"""Merged branches: a repository's local branches whose pull request GitHub merged, the worktree
each is checked out in, and removing them on the developer's confirmation, by the rules
"Merged branches" in `specs/repositories.md` states (ADR-044).

A branch is merged when GitHub reports a pull request from it, in the registered repository, as
merged, and the branch's tip is that pull request's last commit, so a squash merge counts and a
branch committed to since doesn't. GitHub is asked once, for the newest merged pull requests up
to `github.MERGED_PULL_REQUESTS_READ`, within the board's timeout; branches and worktrees are
read from the primary checkout with two git calls whatever their number. A removal is a
worktree's removal as `git worktree remove` does it without forcing, then the branch's deletion,
each checked again at the click and refused where work would be lost, or where what goes isn't
what the developer was shown, as a digest of it that the confirmation carries back tells. The
branch's tip is read again before each step, so one committed to meanwhile stays. A worktree's
path comes from git's own list, never from the request. Nothing else is touched: no
remote-tracking branch, no branch on GitHub, nothing in the repository's git folder.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, github, repositories, sessions, tasks, template_sync
from repocop.services.board import PULL_REQUEST_TIMEOUT_S
from repocop.services.repositories import Repository

LOCAL_PREFIX = "refs/heads/"
CHANGED_SHOWN = 5  # how many of a worktree's changed files a refusal names


@dataclass(frozen=True)
class Worktree:
    """Where a branch is checked out."""

    path: Path  # as git records it
    present: bool  # its folder is there; False when only git's record of it is left
    locked: str | None  # the lock's reason, "" when none was given; None when it isn't locked
    primary: bool  # it is the primary checkout itself


@dataclass(frozen=True)
class MergedBranch:
    name: str
    tip: str
    pull_request: str  # the address of the pull request that merged it
    worktree: Worktree | None


@dataclass(frozen=True)
class Listing:
    """A repository's merged branches, or why they can't be listed."""

    branches: tuple[MergedBranch, ...]  # by name
    error: str | None  # why nothing could be listed; None when it could
    limit_reached: int | None  # how many pull requests were read, when as many as are read at
    # once were, so a branch merged longer ago may be left out; else None


@dataclass(frozen=True)
class Removal:
    """What removing a branch would do now, or why it is refused."""

    branch: str
    tip: str | None  # the commit the branch goes at; None when it isn't merged now
    worktree: Worktree | None
    deletes: tuple[str, ...]  # the ignored files its worktree's removal deletes too
    refused: str | None

    @property
    def digest(self) -> str:
        """A digest of all that removing it deletes: the branch at its tip, its worktree and the
        ignored files in it. Equal digests mean the same goes."""
        worktree = self.worktree
        goes = [
            self.branch,
            self.tip,
            str(worktree.path) if worktree else None,
            worktree.present if worktree else None,
            list(self.deletes),
        ]
        return hashlib.sha256(json.dumps(goes).encode()).hexdigest()


@dataclass(frozen=True)
class Outcome:
    """What removing a branch did."""

    branch: str
    removed: bool
    detail: str  # what went with it, or why it was refused


def read(
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    *,
    timeout: float = PULL_REQUEST_TIMEOUT_S,
) -> Listing:
    """The repository's merged branches now, each with the worktree it is checked out in, from
    GitHub and the primary checkout. A template sync's branch is left out. Read-only."""
    try:
        checkout = repositories.require_checkout(repository, settings)
        on_github = github.repository_of(repository.remote_url)
        github.check_ready(checkout, timeout=timeout)
        pulls = github.merged_pull_requests(checkout, on_github, timeout=timeout)
    except RepoCopError as exc:
        return Listing((), str(exc), None)
    merged_at = {(pull.branch, pull.last_commit): pull.url for pull in reversed(pulls.found)}
    syncs = {
        task.branch
        for task in tasks.list_for_repository(conn, repository, workflow=template_sync.WORKFLOW)
    }
    worktrees = _worktrees(checkout)
    found = []
    for ref, tip in git.branch_tips(checkout).items():
        name = ref.removeprefix(LOCAL_PREFIX)
        url = merged_at.get((name, tip))
        if ref.startswith(LOCAL_PREFIX) and url is not None and name not in syncs:
            found.append(MergedBranch(name, tip, url, worktrees.get(name)))
    limit = github.MERGED_PULL_REQUESTS_READ if pulls.at_limit else None
    return Listing(tuple(sorted(found, key=lambda branch: branch.name)), None, limit)


def plan(
    conn: sqlite3.Connection, settings: Settings, repository: Repository, names: Iterable[str]
) -> list[Removal]:
    """What removing each of the branches `names` would do now, each once, in their order: its
    worktree and the ignored files that go with it, or why it is refused. Everything is read
    again: a branch is merged only as GitHub and the checkout report it at this moment."""
    names = dict.fromkeys(names)
    listing = read(conn, settings, repository)
    if listing.error:
        refused = f"merged branches can't be read: {listing.error}"
        return [Removal(name, None, None, (), refused) for name in names]
    by_name = {branch.name: branch for branch in listing.branches}
    checkout = repositories.require_checkout(repository, settings)
    others = [entry.path for entry in git.worktrees(checkout) if not entry.prunable]
    unclosed = sessions.unclosed(repository, settings)
    return [_removal(name, by_name, unclosed, others) for name in names]


def remove(
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    names: Iterable[str],
    confirmed: Iterable[str],
) -> list[Outcome]:
    """Remove each of the branches `names` that `plan` allows and whose `Removal.digest` is among
    `confirmed`, so nothing goes that the developer wasn't shown: its worktree first, as
    `git worktree remove` does without forcing, then the branch, each while the branch is still at
    the tip it was checked at. One refusal stops nothing else, and nothing but the worktree and
    the branch goes. Only on the developer's confirmation."""
    shown = set(confirmed)
    outcomes = []
    for removal in plan(conn, settings, repository, names):
        if removal.refused:
            outcomes.append(Outcome(removal.branch, False, removal.refused))
            continue
        if removal.digest not in shown:
            changed = "what goes with it has changed since it was shown: show what goes again"
            outcomes.append(Outcome(removal.branch, False, changed))
            continue
        try:
            checkout = repositories.require_checkout(repository, settings)
            outcomes.append(_remove_one(checkout, removal))
        except RepoCopError as exc:
            outcomes.append(Outcome(removal.branch, False, str(exc)))
    return outcomes


def _remove_one(checkout: Path, removal: Removal) -> Outcome:
    worktree = removal.worktree
    if moved := _moved(checkout, removal):
        return Outcome(removal.branch, False, moved)
    if worktree is not None:
        git.remove_worktree(checkout, worktree.path)
        if moved := _moved(checkout, removal):
            return Outcome(removal.branch, False, f"{moved}, though its worktree has gone")
    git.delete_branch(checkout, removal.branch)
    if worktree is None:
        detail = "it had no worktree"
    elif worktree.present:
        detail = f"with its worktree {worktree.path}"
    else:
        detail = (
            f"its worktree at {worktree.path} was already gone, so only git's record of it was "
            "cleared"
        )
    return Outcome(removal.branch, True, detail)


def _moved(checkout: Path, removal: Removal) -> str | None:
    """Why the branch must stay: it was committed to since it was checked. None while it is at
    the tip it was checked at."""
    if git.resolve(checkout, LOCAL_PREFIX + removal.branch) == removal.tip:
        return None
    return "it was committed to since it was checked, so it is no longer merged"


def _removal(
    name: str,
    by_name: dict[str, MergedBranch],
    unclosed: list[sessions.Session],
    others: list[Path],
) -> Removal:
    branch = by_name.get(name)
    if branch is None:
        return Removal(
            name,
            None,
            None,
            (),
            "it isn't merged now: no local branch of that name ends at the last commit of a "
            "pull request GitHub merged",
        )
    worktree = branch.worktree
    if worktree is None:
        return Removal(name, branch.tip, None, (), None)
    try:
        refused = _refusal(worktree, unclosed, others)
        deletes = (
            tuple(git.ignored_files(worktree.path)) if refused is None and worktree.present else ()
        )
    except RepoCopError as exc:
        return Removal(name, branch.tip, worktree, (), f"its worktree can't be read: {exc}")
    return Removal(name, branch.tip, worktree, deletes, refused)


def _refusal(
    worktree: Worktree, unclosed: list[sessions.Session], others: list[Path]
) -> str | None:
    """Why removing `worktree` would lose work or write where RepoCop never does, else None.
    `others` are where the repository's worktrees are, the primary checkout among them."""
    path = worktree.path
    if worktree.primary:
        return "it is checked out in the primary checkout"
    if worktree.locked is not None:
        reason = f": {worktree.locked}" if worktree.locked else ""
        return f"its worktree {path} is locked{reason}"
    if inside := [s for s in unclosed if _within(s.cwd, path)]:
        return f"session {inside[0].id} ({inside[0].state}) is in its worktree {path}"
    if path.is_symlink():
        return f"its worktree {path} isn't a folder of its own"
    held = [other for other in others if other != path and _within(other, path)]
    if held:
        return f"its worktree {path} holds another worktree, {held[0]}, which would go with it"
    if worktree.present and (changed := git.changed_files(path)):
        more = f" and {len(changed) - CHANGED_SHOWN} more" if len(changed) > CHANGED_SHOWN else ""
        return (
            f"its worktree {path} has modified or untracked files "
            f"({', '.join(changed[:CHANGED_SHOWN])}{more})"
        )
    return None


def _within(folder: str | Path, worktree: Path) -> bool:
    """Whether `folder` is `worktree` or inside it."""
    return Path(folder).resolve().is_relative_to(worktree.resolve())


def _worktrees(checkout: Path) -> dict[str, Worktree]:
    """The branch each worktree has checked out, by branch. The main worktree, first in git's
    list, is the primary checkout."""
    found: dict[str, Worktree] = {}
    for index, entry in enumerate(git.worktrees(checkout)):
        if entry.branch is not None:
            present = not entry.prunable and entry.path.is_dir()
            found[entry.branch] = Worktree(entry.path, present, entry.locked, index == 0)
    return found
