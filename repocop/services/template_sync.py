"""Template sync: bring a repository's committed files up to date with the repo template.

It is the one way the template reaches a repository, a new one's first files included (ADR-029).
The plan, `repositories.template_plan`, compares the template with the repository's default
branch on `origin`, as last fetched (ADR-006). The user picks which missing files to create,
which differing ones to overwrite, which merged files to bring up to date with the template
(ADR-021, ADR-027), and which marked files the template no longer ships to delete (ADR-032);
nothing is changed unless picked, and a starter file the repository has is never offered. Picked
files are written, or deleted, and committed on a new branch in a RepoCop-owned worktree,
started from the commit the plan compared with and recorded as a `template-sync` task, and the
primary checkout is never touched. With nothing picked, nothing changes and no branch exists.

A completed sync waits until its files reach `origin`, and no other sync starts meanwhile, so
the same files are never offered on two branches. A completed sync's branch and worktree are
removed only when the user asks.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Collection
from enum import StrEnum
from pathlib import Path

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import bootstrap, git, repositories, tasks, worktrees
from repocop.services.repositories import Repository
from repocop.services.tasks import Status, Task

WORKFLOW = "template-sync"
COMMIT_SUBJECT = "Sync with RepoCop template"


class TemplateSyncError(RepoCopError):
    """A template sync can't be applied as asked."""


class SyncState(StrEnum):
    """Where a completed sync's work stands."""

    WAITING = "waiting"  # to reach origin, and no other sync starts meanwhile
    ON_ORIGIN = "on origin"  # its files are on the default branch there
    NOT_ON_ORIGIN = "not on origin"  # and it no longer waits: a newer sync or template replaced it
    REMOVED = "removed"  # its worktree is gone


def waiting(conn: sqlite3.Connection, settings: Settings, repository: Repository) -> Task | None:
    """The repository's sync that is done but not yet on `origin`: its newest completed sync,
    while that sync's worktree is there and its branch is up to date on a template file that the
    default branch on `origin` isn't, or has deleted a file the template retired that the default
    branch still has. None otherwise.

    It is judged by the files, so a sync merged any way, a squash included, stops waiting once
    the merge is fetched, and so does a sync the template has since moved past.
    """
    newest = next(
        (
            task
            for task in tasks.list_for_repository(conn, repository, workflow=WORKFLOW)
            if task.status is Status.COMPLETED
        ),
        None,
    )
    if newest is None or newest.branch is None:
        return None
    worktree = tasks.worktree(conn, settings, newest)
    if worktree is None:
        return None
    try:
        on_origin = repositories.template_plan(repository, settings)
        checkout = repositories.require_checkout(repository, settings)
        on_branch = bootstrap.sync_plan(
            settings.template_dir, checkout, newest.branch, repository.name
        )
        lacking = {file.path for file in on_origin.files if not file.up_to_date}
        if any(file.up_to_date and file.path in lacking for file in on_branch.files):
            return newest
        # A retired file the branch lacks is this sync's deletion only if the sync changed it:
        # one that reached origin after the sync started was never on its branch.
        gone = {file.path for file in on_origin.retired} - {file.path for file in on_branch.files}
        if not gone or newest.base_commit is None:
            return None
        deleted = gone.intersection(git.files_changed_since(worktree, newest.base_commit))
    except RepoCopError:
        return None
    return newest if deleted else None


def states(
    conn: sqlite3.Connection, settings: Settings, repository: Repository
) -> dict[int, SyncState]:
    """Where each of the repository's completed syncs stands, by task id. A sync is on origin
    when every file it changed has the same content on the default branch there, however it
    was merged."""
    pending = waiting(conn, settings, repository)
    found = {}
    for task in tasks.list_for_repository(conn, repository, workflow=WORKFLOW):
        if task.status is not Status.COMPLETED:
            continue
        worktree = tasks.worktree(conn, settings, task)
        if pending is not None and task.id == pending.id:
            found[task.id] = SyncState.WAITING
        elif worktree is None or task.base_commit is None:
            found[task.id] = SyncState.REMOVED
        else:
            found[task.id] = _landed(repository, worktree, task.base_commit)
    return found


def remove(conn: sqlite3.Connection, settings: Settings, task: Task) -> None:
    """Remove a completed sync's worktree and branch, when the user asks. Refused, keeping
    both, when its worktree has uncommitted changes, is on another branch, or is gone."""
    if task.workflow != WORKFLOW or task.status is not Status.COMPLETED:
        raise TemplateSyncError(f"task #{task.id} isn't a completed template sync")
    repository = repositories.get(conn, task.repository_id)
    worktree = tasks.worktree(conn, settings, task)
    if repository is None or worktree is None or task.branch is None:
        raise TemplateSyncError(f"sync #{task.id} has no worktree to remove")
    try:
        worktrees.remove(repository, settings, worktree, task.branch)
    except worktrees.WorktreeError as exc:
        raise TemplateSyncError(f"sync #{task.id} wasn't removed: {exc}") from exc


def _landed(repository: Repository, worktree: Path, base: str) -> SyncState:
    """Whether the files a sync's branch changed since `base` are on origin's default branch."""
    try:
        changed = git.files_changed_since(worktree, base)
        if not changed:
            return SyncState.ON_ORIGIN
        on_origin = git.same_files(
            worktree, repositories.origin_default(repository), "HEAD", changed
        )
    except git.GitError:
        return SyncState.NOT_ON_ORIGIN
    return SyncState.ON_ORIGIN if on_origin else SyncState.NOT_ON_ORIGIN


def apply(
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    *,
    create: Collection[str],
    overwrite: Collection[str],
    merge: Collection[str] = (),
    delete: Collection[str] = (),
) -> Task | None:
    """Write, or delete, and commit the picked files on a new sync branch, as a template-sync
    task.

    Only files the current plan shows as missing (to create), differing (to overwrite), lacking
    entries (to merge) or removed from the template (to delete) are accepted. A merge is
    computed from the file as the sync branch has it. Returns None when nothing was picked. A
    failure after the task exists fails the task with the reason and keeps its worktree for
    inspection.
    """
    if (pending := waiting(conn, settings, repository)) is not None:
        raise TemplateSyncError(
            f"sync #{pending.id} on {pending.branch} is waiting: push it and merge its pull "
            "request first, then sync again for anything left"
        )
    # The plan and the worktree start from one commit, so a fetch meanwhile can't make the sync
    # write or delete a version of a file the plan never compared.
    checkout = repositories.require_checkout(repository, settings)
    start = git.resolve(checkout, repositories.origin_default(repository))
    current = bootstrap.sync_plan(settings.template_dir, checkout, start, repository.name)
    offered = {
        "create": {file.path for file in current.missing},
        "overwrite": {file.path for file in current.differing},
        "merge": {file.path for file in current.behind},
        "delete": {file.path for file in current.retired},
    }
    picks = {"create": create, "overwrite": overwrite, "merge": merge, "delete": delete}
    unexpected = set().union(*(set(picks[action]) - offered[action] for action in picks))
    if unexpected:
        raise TemplateSyncError(
            f"{', '.join(sorted(unexpected))} can't be synced as picked; reload the plan"
        )
    picked = [(path, action) for action in picks for path in sorted(picks[action])]
    if not picked:
        return None

    task = tasks.create(conn, repository.id, WORKFLOW)
    try:
        name, branch = worktrees.task_names(WORKFLOW, task.id)
        worktree = worktrees.create(repository, settings, name, branch, start=start)
        task = tasks.set_worktree(
            conn, task.id, worktree.branch, worktree.path, worktree.base_commit
        )
        tasks.transition(conn, task.id, Status.RUNNING)
        for path, _ in picked:
            _check_inside(worktree.path, path)
        for path, action in picked:
            if action == "merge":
                _merge(settings.template_dir, worktree.path, path, repository.name)
            elif action == "delete":
                (worktree.path / path).unlink()  # a symlink itself, never what it points at
            else:
                _write(settings.template_dir, worktree.path, path, repository.name)
        message = (
            COMMIT_SUBJECT + "\n\n" + "".join(f"- {action} {path}\n" for path, action in picked)
        )
        git.commit_files(worktree.path, [path for path, _ in picked], message)
        tasks.record(conn, task.id, "raw", {"text": message})
        return tasks.transition(conn, task.id, Status.COMPLETED)
    except (RepoCopError, OSError) as exc:
        tasks.record(conn, task.id, "error", {"error": str(exc)})
        return tasks.transition(conn, task.id, Status.FAILED, error=str(exc))


def _check_inside(worktree: Path, path: str) -> None:
    """Refuse a file whose folder resolves outside the worktree, e.g. through a symlink."""
    if not (worktree / path).parent.resolve().is_relative_to(worktree.resolve()):
        raise TemplateSyncError(
            f"{path} is outside the worktree (through a symlink), so nothing was written"
        )


def _write(template_dir: Path, worktree: Path, path: str, repo_name: str) -> None:
    target = worktree / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()  # overwrite the link itself, never whatever it points at
    target.write_bytes(bootstrap.rendered(template_dir, path, repo_name))
    shutil.copymode(template_dir / path, target)


def _merge(template_dir: Path, worktree: Path, path: str, repo_name: str) -> None:
    """Bring the worktree's file up to date with the template, keeping its mode."""
    target = worktree / path
    if target.is_symlink():
        raise TemplateSyncError(f"{path} is a symlink, so nothing was merged into it")
    try:
        merged = bootstrap.merge(template_dir, path, repo_name, target.read_bytes())
    except bootstrap.MergeError as exc:
        raise TemplateSyncError(f"{path} can't be merged: {exc}") from exc
    target.write_bytes(merged)
