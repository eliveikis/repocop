"""The fleet's board: every requirement in each registered repository by its stage, read from the
repository itself and from GitHub, however and by whomever the work was done (ADR-038).

A requirement is in the first stage that applies:

- Delivered: archived within the past week by its archive stamp, in the checkout or on the
  default branch on `origin` as last fetched.
- In review: a branch that belongs to it has an open pull request.
- In progress: a branch that belongs to it has commits that default branch lacks.
- To do: anything else in the requirements folder.

A branch belongs to a requirement by its name (the branch rule in `.claude/rules/specs.md`),
whoever made it, local or on `origin`. Branches are read with a fixed number of git calls,
whatever their number. Nothing here fetches, or writes on disk or on GitHub.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import backlog, git, github, repositories, requirements
from repocop.services.repositories import Repository

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
    delivered_at: datetime | None = None


@dataclass(frozen=True)
class Note:
    """What a repository's cards can't show, and why."""

    repository: Repository
    text: str


@dataclass(frozen=True)
class Board:
    cards: tuple[Card, ...]
    notes: tuple[Note, ...]
    with_pull_requests: bool  # whether GitHub was asked for pull requests

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
    for repository in shown:
        try:
            found, more = _cards(settings, repository, pulls.get(repository.id, {}))
        except RepoCopError as exc:
            notes.append(Note(repository, str(exc)))
            continue
        cards += found
        notes += more
    return Board(tuple(cards), tuple(notes), with_pull_requests)


def belongs(branch: str, names: Iterable[str]) -> bool:
    """Whether `branch` belongs to a requirement called any of `names`: it is that name, alone or
    after its last `/` (`.claude/rules/specs.md`)."""
    return branch.rpartition("/")[2] in set(names)


def _cards(
    settings: Settings,
    repository: Repository,
    pulls: Mapping[str, str],
) -> tuple[list[Card], list[Note]]:
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
            Card(repository, name, page if linked else None, Stage.DELIVERED, delivered_at=when)
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
        if any(branch.pull_request for branch in branches):
            stage = Stage.IN_REVIEW
        elif any(branch.ahead for branch in branches):
            stage = Stage.IN_PROGRESS
        else:
            stage = Stage.TO_DO
        waits_on = tuple((need.name, ordered.pages.get(need.name)) for need in change.waits_on)
        cards.append(Card(repository, change.name, change.file, stage, branches, waits_on))
    return cards, notes


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
