"""The fleet's board: every requirement in each registered repository by its stage, read from the
repository itself and from GitHub, however and by whomever the work was done (ADR-038).

A requirement is in the first stage that applies:

- Delivered: archived within the past week by its archive stamp, in the checkout or on the
  default branch on `origin` as last fetched.
- In review: a branch that belongs to it has an open pull request.
- In progress: a branch that belongs to it has commits that default branch lacks, or a session
  working on it is working, needs input or waits for an instruction.
- To do: anything else in the requirements folder.

A branch belongs to a requirement by its name (the branch rule in `.claude/rules/specs.md`),
whoever made it, local or on `origin`. Branches are read with a fixed number of git calls,
whatever their number. A card shows the sessions that work on its requirement, and a repository's
other sessions show apart, so none goes unseen. Nothing here fetches, or writes on disk or on
GitHub.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import backlog, git, github, repositories, requirements, sessions
from repocop.services.repositories import Repository
from repocop.services.sessions import Session

DELIVERED_SHOWN = timedelta(days=7)  # how long a delivered change stays on the board
PULL_REQUEST_TIMEOUT_S = 15.0  # how long the board waits for GitHub, for each repository
PULL_REQUEST_READS_AT_ONCE = 8  # how many repositories' pull requests are read side by side
LOCAL_PREFIX = "refs/heads/"
ORIGIN_PREFIX = "refs/remotes/origin/"


class Stage(StrEnum):
    TO_DO = "To do"
    IN_PROGRESS = "In progress"
    IN_REVIEW = "In review"
    DELIVERED = "Delivered"

    @property
    def slug(self) -> str:
        return self.value.lower().replace(" ", "-")


@dataclass(frozen=True)
class Branch:
    """A branch that belongs to a requirement, local or on `origin` or both, by its name there."""

    name: str
    ahead: int | None  # commits the default branch on origin lacks; None when it isn't fetched
    on_origin: bool  # origin has every commit it has
    pull_request: str | None = None  # the address of its open pull request


@dataclass(frozen=True)
class Card:
    repository: Repository
    name: str
    page: str | None  # the file name its page is found by; None when the checkout has none
    stage: Stage
    branches: tuple[Branch, ...] = ()
    waits_on: tuple[tuple[str, str | None], ...] = ()  # undelivered needs: name, page file
    sessions: tuple[Session, ...] = ()  # those working on it, the latest first
    delivered_at: datetime | None = None
    held_up: bool = False  # a dependency problem keeps it from being ordered


@dataclass(frozen=True)
class Note:
    """What a repository's cards can't show, and why."""

    repository: Repository
    text: str
    about_sessions: bool = False  # it says why sessions aren't shown, not why cards can't be


@dataclass(frozen=True)
class Board:
    cards: tuple[Card, ...]
    notes: tuple[Note, ...]
    with_pull_requests: bool  # whether GitHub was asked for pull requests
    # Each repository's sessions that work on no requirement with a card, by repository id.
    others: Mapping[int, tuple[Session, ...]] = field(default_factory=dict)
    # What keeps each repository's changes from being ordered, by repository id.
    problems: Mapping[int, tuple[backlog.Problem, ...]] = field(default_factory=dict)

    @property
    def columns(self) -> tuple[tuple[Stage, tuple[Card, ...]], ...]:
        """Each stage, in the board's order, with its cards."""
        return tuple((stage, self.stage(stage)) for stage in Stage)

    def stage(self, stage: Stage) -> tuple[Card, ...]:
        """The cards in `stage`: by repository, then in the order they can start; delivered
        ones newest first."""
        found = tuple(card for card in self.cards if card.stage is stage)
        if stage is Stage.DELIVERED:
            return tuple(sorted(found, key=lambda card: card.delivered_at or _EPOCH, reverse=True))
        return found

    def counts(self, repository_id: int) -> tuple[tuple[Stage, int], ...]:
        """How many of the repository's cards are in each stage, in the board's order."""
        mine = [card.stage for card in self.cards if card.repository.id == repository_id]
        return tuple((stage, mine.count(stage)) for stage in Stage)

    def apart_from(self, stages: Iterable[Stage]) -> dict[int, tuple[Session, ...]]:
        """Each repository's sessions that work on no requirement with a card in `stages`, the
        latest first."""
        shown = set(stages)
        apart = {repository_id: list(found) for repository_id, found in self.others.items()}
        for card in self.cards:
            if card.stage not in shown:
                apart.setdefault(card.repository.id, []).extend(card.sessions)
        return {
            repository_id: tuple(sorted(found, key=lambda s: s.since, reverse=True))
            for repository_id, found in apart.items()
        }


_EPOCH = datetime.fromtimestamp(0, UTC)


def read(
    settings: Settings,
    listed: Iterable[Repository],
    *,
    with_pull_requests: bool,
) -> Board:
    """The board of every repository in `listed` whose checkout is there. With
    `with_pull_requests`, GitHub is asked for each one's open pull requests, side by side."""
    shown = [r for r in listed if repositories.checkout_present(r, settings)]
    notes: list[Note] = []
    pulls: dict[int, dict[str, str]] = {}
    if with_pull_requests:
        pulls, unread = _open_pull_requests(settings, shown)
        notes += unread
    cards: list[Card] = []
    others: dict[int, tuple[Session, ...]] = {}
    problems: dict[int, tuple[backlog.Problem, ...]] = {}
    for repository in shown:
        working = sessions.of(repository, settings)
        try:
            found, more, wrong = _cards(settings, repository, pulls.get(repository.id, {}), working)
        except RepoCopError as exc:
            notes.append(Note(repository, str(exc)))
            found, more, wrong = [], [], ()
        cards += found
        notes += more
        problems[repository.id] = wrong
        shown_on = {card.name for card in found}
        others[repository.id] = tuple(s for s in working if s.requirement not in shown_on)
    return Board(tuple(cards), tuple(notes), with_pull_requests, others, problems)


def belongs(branch: str, names: Iterable[str]) -> bool:
    """Whether `branch` belongs to a requirement called any of `names`: it is that name, alone or
    after its last `/` (`.claude/rules/specs.md`)."""
    return branch.rpartition("/")[2] in set(names)


def _cards(
    settings: Settings,
    repository: Repository,
    pulls: Mapping[str, str],
    working: Iterable[Session],
) -> tuple[list[Card], list[Note], tuple[backlog.Problem, ...]]:
    checkout = repositories.require_checkout(repository, settings)
    todo, archived_here = requirements.change_files(settings, repository)
    default = repositories.origin_default(repository)
    notes: list[Note] = []
    try:
        git.resolve(checkout, default)
        fetched = True
    except git.GitError:
        fetched = False
        if todo:
            notes.append(
                Note(
                    repository,
                    f"{default} isn't in {repository.name}'s checkout. Fetch first: until then "
                    "its cards show no branch state.",
                )
            )
    if fetched and sessions.recorder_on_origin(repository, settings) is False:
        notes.append(
            Note(
                repository,
                f"{default} lacks the hook that records agent sessions, so its sessions aren't "
                "shown. A template sync brings it, and sessions on branches made before that "
                "sync record nothing.",
                about_sessions=True,
            )
        )
    archived_there: list[str] = []
    if fetched:
        try:
            archived_there = _archived_on(checkout, default, repository)
        except git.GitError as exc:  # a partial clone lacks the folder: nothing is downloaded
            notes.append(
                Note(repository, f"its delivered changes on {default} can't be read: {exc}")
            )
    # A change origin archived is delivered, whatever age, even while the checkout, not yet
    # brought up to date, still has it in its folder: that copy isn't a change still to do.
    delivered_there = {backlog.name_of(file) for file in archived_there}
    pending = {
        file: text for file, text in todo.items() if backlog.name_of(file) not in delivered_there
    }
    # a file archived in the checkout and on origin is one delivered change, not two
    ordered = backlog.order(pending, sorted({*archived_here, *archived_there}))

    cards: list[Card] = []
    delivered: set[str] = set()
    for file, when in _delivered(archived_here, archived_there).items():
        name = backlog.name_of(file)
        delivered.add(name)
        page = file[stamp.end() :] if (stamp := requirements.ARCHIVE_STAMP.match(file)) else file
        linked = file in archived_here or page in todo
        cards.append(
            Card(
                repository,
                name,
                page if linked else None,
                Stage.DELIVERED,
                sessions=sessions.for_requirement(working, name),
                delivered_at=when,
            )
        )

    changes = [
        change
        for change in (*(c for level in ordered.levels for c in level), *ordered.apart)
        if change.name not in delivered
    ]
    tips = git.branch_tips(checkout) if fetched else {}
    belonging = {change.file: _belonging(change, tips, pulls) for change in changes}
    local_tips = [local for refs in belonging.values() for _, local, _ in refs if local]
    origin_tips = [there for refs in belonging.values() for _, _, there in refs if there]
    ahead = git.commits_ahead(checkout, [*local_tips, *origin_tips], default)
    pushed = git.on_origin(checkout, local_tips)
    for change in changes:
        branches = tuple(
            _branch(name, local, there, ahead, pushed, pulls)
            for name, local, there in belonging[change.file]
        )
        on_it = sessions.for_requirement(working, change.name)
        if any(branch.pull_request for branch in branches):
            stage = Stage.IN_REVIEW
        elif any(branch.ahead for branch in branches) or any(s.live for s in on_it):
            stage = Stage.IN_PROGRESS
        else:
            stage = Stage.TO_DO
        waits_on = tuple((need.name, ordered.pages.get(need.name)) for need in change.waits_on)
        cards.append(
            Card(
                repository,
                change.name,
                change.file,
                stage,
                branches,
                waits_on,
                on_it,
                held_up=change in ordered.apart,
            )
        )
    return cards, notes, ordered.problems


def _branch(
    name: str,
    local: str | None,
    there: str | None,
    ahead: Mapping[str, int],
    pushed: set[str],
    pulls: Mapping[str, str],
) -> Branch:
    """A belonging branch as its card shows it: the local tip counts when there is one, since
    that is the work the developer has, else `origin`'s."""
    tip = local or there
    return Branch(
        name, ahead[tip] if tip else None, local is None or local in pushed, pulls.get(name)
    )


def _belonging(
    change: backlog.Change, tips: Mapping[str, str], pulls: Mapping[str, str]
) -> list[tuple[str, str | None, str | None]]:
    """The branches that belong to `change`, by name: each one's local and `origin` tips, either
    None when it isn't there. A branch with an open pull request counts even before it's fetched."""
    names = {change.name, PurePosixPath(change.file).stem}
    found: dict[str, list[str | None]] = {}
    for ref, sha in tips.items():
        for prefix, side in ((LOCAL_PREFIX, 0), (ORIGIN_PREFIX, 1)):
            if ref.startswith(prefix) and belongs(branch := ref.removeprefix(prefix), names):
                found.setdefault(branch, [None, None])[side] = sha
    for branch in pulls:
        if belongs(branch, names):
            found.setdefault(branch, [None, None])
    return [(name, local, there) for name, (local, there) in sorted(found.items())]


def _delivered(archived_here: Iterable[str], archived_there: Iterable[str]) -> dict[str, datetime]:
    """The archived changes stamped within the past week, by file name, with their stamp: the
    latest of each name, from the checkout and from the default branch on `origin`."""
    now = datetime.now(UTC)
    latest: dict[str, tuple[datetime, str]] = {}
    for file in {*archived_here, *archived_there}:
        if (stamp := requirements.ARCHIVE_STAMP.match(file)) is None:
            continue
        try:
            when = datetime.strptime(stamp[0], "%Y-%m-%dT%H%M%SZ-").replace(tzinfo=UTC)
        except ValueError:  # shaped like a stamp, but not a time: as if it had none
            continue
        name = backlog.name_of(file)
        if now - when <= DELIVERED_SHOWN and (name not in latest or latest[name][0] < when):
            latest[name] = (when, file)
    return {file: when for when, file in latest.values()}


def _archived_on(checkout: Path, ref: str, repository: Repository) -> list[str]:
    """The file names in the archive folder on `ref`."""
    folder = PurePosixPath(requirements.archive_dir(repository))
    return [
        path.name
        for path in map(PurePosixPath, git.files_at(checkout, ref, str(folder)))
        if path.parent == folder and path.suffix == ".md"
    ]


def _open_pull_requests(
    settings: Settings, shown: list[Repository]
) -> tuple[dict[int, dict[str, str]], list[Note]]:
    """Each repository's open pull requests by branch, read side by side, and a note for each
    repository whose pull requests can't be read, saying why."""

    def read_one(repository: Repository) -> dict[str, str]:
        checkout = repositories.require_checkout(repository, settings)
        on_github = github.repository_of(repository.remote_url)
        github.check_ready(checkout, timeout=PULL_REQUEST_TIMEOUT_S)
        return github.open_pull_requests(checkout, on_github, timeout=PULL_REQUEST_TIMEOUT_S)

    workers = max(1, min(PULL_REQUEST_READS_AT_ONCE, len(shown)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        reads = {repository: pool.submit(read_one, repository) for repository in shown}
    found: dict[int, dict[str, str]] = {}
    notes: list[Note] = []
    for repository, done in reads.items():
        try:
            found[repository.id] = done.result()
        except RepoCopError as exc:
            notes.append(Note(repository, str(exc)))
    return found, notes
