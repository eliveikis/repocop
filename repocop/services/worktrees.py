"""Worktrees: RepoCop-owned git worktrees, one per template sync.

A sync's worktree is `<worktrees_root>/<repo>/<name>` on branch `agent/<name>`, where `<name>`
is `template-sync-<task id>`. Every branch RepoCop names starts `agent/`, so it is told apart
from a person's at a glance. Worktrees always sit in their repository's RepoCop-owned folder,
never in a human-owned checkout, and are never deleted automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, repositories
from repocop.services.repositories import Repository


class WorktreeError(RepoCopError):
    """A worktree can't be created where or how it was asked."""


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    base_commit: str  # the primary checkout's HEAD when the worktree was created


MAX_DIFF_TEXT = 200_000
BRANCH_PREFIX = "agent/"  # every branch RepoCop names


@dataclass(frozen=True)
class Changes:
    """What a worktree shows now: `git status`, and the diff of everything since its base."""

    status: str
    diff: str
    clipped: bool  # part of the diff was left out (see `git.diff_since`)


def task_names(workflow: str, task_id: int) -> tuple[str, str]:
    """(folder name, branch) for the worktree of the task `task_id`, running `workflow`."""
    name = f"{workflow}-{task_id}"
    return name, f"{BRANCH_PREFIX}{name}"


def create(
    repository: Repository,
    settings: Settings,
    name: str,
    branch: str,
    *,
    start: str | None = None,
) -> Worktree:
    """A new worktree `name` on a new branch `branch`, starting at `start` (a branch or commit)
    or else the primary checkout's HEAD.

    Refused if the folder or the branch already exists: neither is reused or replaced.
    """
    checkout = repositories.require_checkout(repository, settings)
    path = _path_for(repository, settings, name)
    if path.exists() or path.is_symlink():
        raise WorktreeError(f"{path} already exists, so it was left as it is")
    if git.branch_exists(checkout, branch):
        raise WorktreeError(
            f"branch {branch} already exists in {checkout} and RepoCop didn't create "
            "it for this task, so it won't reuse it"
        )
    base = git.resolve(checkout, start) if start else git.head_commit(checkout)
    path.parent.mkdir(parents=True, exist_ok=True)
    git.add_worktree(checkout, path, branch, base)
    return Worktree(path, branch, base)


def remove(repository: Repository, settings: Settings, path: Path, branch: str) -> None:
    """Remove the worktree at `path` and delete `branch`, the branch it was made on.

    Only on an explicit request: nothing removes a worktree on its own. Refused unless `path`
    is one of the repository's RepoCop worktrees, on `branch`, with nothing uncommitted.
    """
    if not is_worktree(repository, settings, path):
        raise WorktreeError(f"{path} isn't a RepoCop worktree of {repository.name}")
    if (current := git.current_branch(path)) != branch:
        raise WorktreeError(f"{path} is on {current or 'a detached HEAD'}, not {branch}")
    if changed := git.changed_files(path):
        raise WorktreeError(
            f"{path} has uncommitted changes ({', '.join(changed[:5])}), so it was left as it is"
        )
    checkout = repositories.require_checkout(repository, settings)
    git.remove_worktree(checkout, path)
    git.delete_branch(checkout, branch)


def is_worktree(repository: Repository, settings: Settings, path: Path) -> bool:
    """True if `path` is one of this repository's worktrees, in its RepoCop-owned folder.

    It must be a real folder (not a symlink) at that place, and a worktree of the primary
    checkout, which itself must still hold the registered repository: not some other checkout
    moved into either place.
    """
    try:
        expected = _path_for(repository, settings, path.name)
        primary = repositories.require_checkout(repository, settings)
    except (WorktreeError, repositories.RepositoryError):
        return False
    if path != expected or path.is_symlink() or not git.is_checkout(path):
        return False
    try:
        return git.common_dir(path) == git.common_dir(primary)
    except git.GitError:
        return False


def changes(repository: Repository, settings: Settings, path: Path, base: str) -> Changes | None:
    """Git status and the diff since `base` for one of the repo's worktrees; None if it's gone."""
    if not is_worktree(repository, settings, path):
        return None
    diff = git.diff_since(path, base, limit=MAX_DIFF_TEXT)
    return Changes(git.short_status(path), diff.text, diff.clipped)


def _path_for(repository: Repository, settings: Settings, name: str) -> Path:
    """`<worktrees_root>/<repo>/<name>`, refused unless it resolves to exactly that place."""
    expected_root = settings.worktrees_root / repository.name
    path = repository.worktrees_root / name
    root_in_place = expected_root.resolve().parent == settings.worktrees_root.resolve()
    inside_root = path.resolve().parent == expected_root.resolve()
    outside_repos = not path.resolve().is_relative_to(settings.repos_root.resolve())
    in_place = repository.worktrees_root == expected_root and root_in_place and inside_root
    if not in_place or not outside_repos:
        raise WorktreeError(
            f"{path} isn't in RepoCop-owned folder {expected_root}, so no worktree "
            "was created there"
        )
    return path
