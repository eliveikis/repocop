"""Branch reviews: a requirement's branch reviewed before its pull request, by an agent's own
built-in review (ADR-025). Today that agent is Codex.

A review is a task of RepoCop's own on the requirement's branch. It takes its turn in the
requirement's worktree, so nothing else changes the branch meanwhile. It covers the branch's
commits against `origin/<default branch>` as last fetched, and never fetches. It is refused,
before anything runs: before the requirement's first task, while another of its tasks is active,
when the reviewer isn't installed or signed in, when the base isn't there, when the worktree has
uncommitted changes, which the review would otherwise include, and when the branch has no commits
of its own.

A review changes nothing: the worktree's state is taken before it and compared after. A finished
review records the commit it covered, so a page can say when the branch has moved on since.

A finished review can be addressed: the repository's `address-review` skill is started on the
requirement as an ordinary task, and that task is handed the review as it starts.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import codex, git, repositories, requirements, tasks, worktrees
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement
from repocop.services.tasks import Status, Task

WORKFLOW = codex.WORKFLOW
REVIEWER = codex.NAME
ADDRESS_WORKFLOW = "address-review"  # the repository skill that acts on a review
MAX_FILES_NAMED = 5


class ReviewError(RepoCopError):
    """A review can't be started as asked."""


@dataclass(frozen=True)
class Subject:
    """What a review covers: a worktree's head against a base, with nothing uncommitted."""

    base: str
    head: str


@dataclass(frozen=True)
class Latest:
    """A requirement's last finished review."""

    task_id: int
    commit: str  # the branch's head when it was reviewed
    finished_at: str
    text: str  # the review, as the reviewer wrote it
    head: str | None  # the branch's head now; None when its worktree is gone

    @property
    def moved_on(self) -> bool:
        """True when the branch has commits the review didn't cover."""
        return self.head is not None and self.head != self.commit


def is_review(task: Task) -> bool:
    return task.workflow == WORKFLOW


def base_of(repository: Repository) -> str:
    """The ref a review of the repository's branches compares with."""
    return repositories.origin_default(repository)


def start(conn: sqlite3.Connection, settings: Settings, requirement: Requirement) -> Task:
    """Queue a review of the requirement's branch. The module docstring lists what refuses it."""
    repository = repositories.get(conn, requirement.repository_id)
    if repository is None:
        raise ReviewError(f"{requirement.name}'s repository is no longer registered")
    previous = tasks.last_with_worktree(conn, requirement)
    if previous is None or previous.worktree_path is None:
        raise ReviewError(f"{requirement.name} has no branch yet: its first task creates one")
    if tasks.active_task(conn, requirement) is None:  # else the start below says which task
        subject(settings, repository, previous.worktree_path)
    return tasks.start_on_branch(conn, settings, requirement, WORKFLOW)


def subject(settings: Settings, repository: Repository, worktree: Path) -> Subject:
    """What a review of `worktree` would cover now. Refused when it can't be reviewed."""
    if not worktrees.is_worktree(repository, settings, worktree):
        raise ReviewError(f"the worktree {worktree} is gone, so there is no branch to review")
    codex.check_ready(worktree)
    base = base_of(repository)
    try:
        git.resolve(worktree, base)
    except git.GitError:
        raise ReviewError(
            f"{base} isn't in {repository.name}'s checkout. Fetch it first: a review doesn't fetch."
        ) from None
    if changed := git.changed_files(worktree):
        named = ", ".join(changed[:MAX_FILES_NAMED]) + (
            ", …" if len(changed) > MAX_FILES_NAMED else ""
        )
        raise ReviewError(
            f"{worktree} has uncommitted changes ({named}), which a review would include. "
            "Commit or discard them first."
        )
    if git.commits_since(worktree, base) == 0:
        raise ReviewError(f"the branch has no commits that {base} lacks, so nothing to review")
    return Subject(base, git.head_commit(worktree))


def state(worktree: Path) -> tuple[str, str]:
    """The worktree's head and `git status`: the same after a review that changed nothing."""
    return git.head_commit(worktree), git.short_status(worktree)


def latest(conn: sqlite3.Connection, settings: Settings, requirement: Requirement) -> Latest | None:
    """The requirement's last finished review, or None when it has none."""
    finished = _last_finished(conn, requirement)
    if finished is None:
        return None
    task, commit, text = finished
    path = tasks.worktree(conn, settings, task)
    try:
        head = git.head_commit(path) if path else None
    except git.GitError:
        head = None
    return Latest(task.id, commit, task.updated_at, text, head)


def address(conn: sqlite3.Connection, settings: Settings, requirement: Requirement) -> Task:
    """Queue the repository's `address-review` skill on the requirement, to act on its last
    finished review. Refused when it has none, when its branch was made before the repository
    had the skill, and whenever a skill's task would be."""
    if _last_finished(conn, requirement) is None:
        raise ReviewError(f"{requirement.name} has no finished review to address")
    previous = tasks.last_with_worktree(conn, requirement)
    skill = f"{tasks.SKILLS_FOLDER}/{ADDRESS_WORKFLOW}/{tasks.SKILL_FILE}"
    # Git runs only in a worktree that is still the requirement's; the start below refuses others.
    worktree = tasks.worktree(conn, settings, previous) if previous is not None else None
    if worktree is not None:
        try:
            missing = git.read_file(worktree, "HEAD", skill) is None
        except git.GitError:
            missing = False  # the start below says what is wrong with the worktree
        if missing:
            raise ReviewError(
                f"{requirement.name}'s branch doesn't have the {ADDRESS_WORKFLOW} skill yet. "
                "Bring the default branch into it first."
            )
    return tasks.start(conn, settings, requirement, ADDRESS_WORKFLOW)


def handover(conn: sqlite3.Connection, task: Task) -> str | None:
    """What a task that addresses a review is given as it starts: its requirement's last
    finished review, and the commit that review covered. None for any other task."""
    if task.workflow != ADDRESS_WORKFLOW or task.requirement_id is None:
        return None
    requirement = requirements.get(conn, task.requirement_id)
    finished = _last_finished(conn, requirement) if requirement else None
    if finished is None:
        return None
    _, commit, text = finished
    return f"{REVIEWER}'s review of this branch at commit {commit[:12]}:\n\n{text}"


def _last_finished(
    conn: sqlite3.Connection, requirement: Requirement
) -> tuple[Task, str, str] | None:
    """(task, commit covered, review text) of the requirement's last finished review."""
    finished = (
        task
        for task in tasks.list_for_requirement(conn, requirement)
        if is_review(task) and task.status is Status.COMPLETED
    )
    task = next(finished, None)
    if task is None:
        return None
    events = tasks.events_after(conn, task.id, 0)
    changes = [e for e in events if e.kind == "status_change"]
    covered = changes[-1].payload.get("review") if changes else None
    commit = covered.get("commit") if isinstance(covered, dict) else None
    said = [e.payload.get("text") for e in events if e.kind == "assistant_text"]
    if not isinstance(commit, str) or not said or not isinstance(said[-1], str):
        return None
    return task, commit, said[-1]
