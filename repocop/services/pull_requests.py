"""Pull requests: push a completed template sync's branch and open its pull request on GitHub.

Each action runs once, when asked, and nothing else pushes or asks GitHub: what a pull request
has become since is learnt at the next action. An action is refused, before anything is pushed
or asked of GitHub, when the sync didn't complete, when its worktree is gone, on another branch
or has uncommitted changes, when `origin` isn't on github.com or pushes to any repository but
the registered remote, and when the GitHub CLI is missing or logged out. A push is never forced.

The database keeps only the address of the pull request a branch last had open (invariant 4).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, github, repositories, template_sync, worktrees
from repocop.services.repositories import Repository
from repocop.services.tasks import Status, Task

SYNC_TITLE = "Sync with the repo template"


class PullRequestError(RepoCopError):
    """A pull request action can't be done as asked."""


class Action(StrEnum):
    OPEN = "open"  # push the branch and open its pull request
    PUSH = "push"  # send new commits to the pull request's branch
    REVIEW = "review"  # ask Copilot to review the pull request


@dataclass(frozen=True)
class PullRequest:
    repository_id: int
    branch: str
    url: str
    created_at: str


@dataclass(frozen=True)
class Source:
    """A completed sync's branch, which a pull request is opened from."""

    repository: Repository
    branch: str
    worktree: Path
    base_commit: str


def has_own(task: Task) -> bool:
    """True for a task whose branch gets a pull request of its own: a completed template sync."""
    return task.workflow == template_sync.WORKFLOW and task.status is Status.COMPLETED


def of_sync(conn: sqlite3.Connection, task: Task) -> Source:
    """The template sync's branch. Refused unless the sync completed."""
    if task.workflow != template_sync.WORKFLOW:
        raise PullRequestError(f"task #{task.id} isn't a template sync")
    if not has_own(task):
        raise PullRequestError(
            f"template sync #{task.id} is {task.status}: only a completed one has a pull request"
        )
    if task.branch is None or task.worktree_path is None or task.base_commit is None:
        raise PullRequestError(f"task #{task.id} has no worktree, so no branch to push")
    repository = repositories.get(conn, task.repository_id)
    if repository is None:
        raise PullRequestError("the repository is no longer registered")
    return Source(repository, task.branch, task.worktree_path, task.base_commit)


def perform(
    conn: sqlite3.Connection, settings: Settings, source: Source, action: Action
) -> PullRequest:
    """Do one action for the branch's pull request, and return the pull request.

    GitHub is asked first for the branch's open pull request, and that one is remembered,
    whoever opened it. Opening pushes the branch first, and is refused when one is open already.
    Pushing and asking for a review are refused when none is open, as after a merge: opening
    then makes a new one. The module docstring lists what refuses every action.
    """
    repository = _check(settings, source)
    remembered = get(conn, source.repository.id, source.branch)
    found = github.pull_request_of(source.worktree, repository, source.branch)
    if found and (remembered is None or remembered.url != found):
        remembered = _store(conn, source, found)
    if action is Action.OPEN:
        if found:
            raise PullRequestError(f"{source.branch} already has an open pull request: {found}")
        git.push(source.worktree, source.branch)
        url = github.create_pull_request(
            source.worktree,
            repository,
            head=source.branch,
            base=source.repository.default_branch,
            title=SYNC_TITLE,
            body=_body(source),
        )
        return _store(conn, source, url)
    if remembered is None:
        raise PullRequestError(f"{source.branch} has no open pull request. Open one first.")
    if not found:
        raise PullRequestError(
            f"{remembered.url} is no longer open on GitHub. Open a new pull request for "
            f"{source.branch} to carry on."
        )
    if action is Action.PUSH:
        git.push(source.worktree, source.branch)
    else:
        github.request_copilot_review(source.worktree, remembered.url)
    return remembered


def get(conn: sqlite3.Connection, repository_id: int, branch: str) -> PullRequest | None:
    """The pull request last opened or found for the branch, if any."""
    row = conn.execute(
        "SELECT * FROM pull_requests WHERE repository_id = ? AND branch = ?",
        (repository_id, branch),
    ).fetchone()
    return _from_row(row) if row else None


def _check(settings: Settings, source: Source) -> str:
    """Refuse unless the branch can be pushed and GitHub asked. Returns `owner/name` there."""
    path, branch = source.worktree, source.branch
    if not worktrees.is_worktree(source.repository, settings, path):
        raise PullRequestError(f"the worktree {path} is gone, so {branch} can't be pushed from it")
    if (current := git.current_branch(path)) != branch:
        raise PullRequestError(
            f"the worktree {path} is on {current or 'a detached HEAD'}, not {branch}"
        )
    if changed := git.changed_files(path):
        files = "1 file" if len(changed) == 1 else f"{len(changed)} files"
        raise PullRequestError(
            f"the worktree {path} has {files} with uncommitted changes. Commit or discard them "
            "first, so the pull request shows all the work."
        )
    remote = source.repository.remote_url
    repository = github.repository_of(remote)
    identity = git.remote_identity(remote)
    if elsewhere := [url for url in git.push_urls(path) if git.remote_identity(url) != identity]:
        raise PullRequestError(
            f"origin pushes to {' and '.join(elsewhere)}, but the pull request is opened on "
            f"{remote}. Nothing was pushed."
        )
    github.check_ready(path)
    return repository


def _body(source: Source) -> str:
    """The pull request's text: the files the branch changed."""
    files = git.files_changed_since(source.worktree, source.base_commit)
    return "Files changed:\n\n" + "".join(f"- `{file}`\n" for file in files)


def _store(conn: sqlite3.Connection, source: Source, url: str) -> PullRequest:
    with db.transaction(conn):
        row = conn.execute(
            "INSERT INTO pull_requests (repository_id, branch, url, created_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (repository_id, branch) DO UPDATE SET"
            " url = excluded.url, created_at = excluded.created_at RETURNING *",
            (source.repository.id, source.branch, url, db.timestamp()),
        ).fetchone()
    return _from_row(row)


def _from_row(row: sqlite3.Row) -> PullRequest:
    return PullRequest(row["repository_id"], row["branch"], row["url"], row["created_at"])
