"""A repository's backlog: the changes in its requirements folder, ordered by what each needs
delivered first.

A change lists those in front matter, one name per line under `depends-on:`. A change's name is
its file name without `.md`, its archive stamp, and the `req-<id>-` prefix older changes carry, so
it survives the change being archived. A dependency in the archive is delivered. The
changes are grouped by level: those that can start now, then those one undelivered change away,
and so on, by their longest chain. A name that matches no change or more than one, a change that
needs itself, a cycle, or a `depends-on` that can't be read is a problem: the changes it
involves, and those that wait on them, are listed apart.

The template's `specs/changes/backlog.sh` draws the backlog by the same rules, with the same
problems, so the two change together (`.claude/rules/specs.md`).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from repocop.config import Settings
from repocop.services import requirements
from repocop.services.repositories import Repository
from repocop.services.requirements import Detail, Requirement, RequirementError

ID_PREFIX = re.compile(r"req-[0-9]+-")
LIST_START = re.compile(r"depends-on:[ \t]*")
LIST_ITEM = re.compile(r"[ \t]*-[ \t]+([^ \t]+)[ \t]*")
UNREAD = "can't be read inside the checkout"


class Unreadable(Exception):
    """A change's `depends-on` can't be read, saying why."""


@dataclass(frozen=True)
class Need:
    """A name in a change's `depends-on`, and what it matches."""

    name: str
    file: str | None  # the undelivered change it matches, by file name
    delivered: bool  # it matches a delivered change


@dataclass(frozen=True)
class Change:
    file: str  # its file name in the requirements folder
    name: str
    needs: tuple[Need, ...]
    delivered: bool = False

    @property
    def waits_on(self) -> tuple[Need, ...]:
        """What it needs that isn't delivered, including names that match nothing."""
        return tuple(need for need in self.needs if not need.delivered)


@dataclass(frozen=True)
class Problem:
    names: tuple[str, ...]  # the changes it's about
    text: str

    def __str__(self) -> str:
        return f"{', '.join(self.names)}: {self.text}"


@dataclass(frozen=True)
class Backlog:
    changes: tuple[Change, ...]  # every change not delivered yet, by file name
    levels: tuple[tuple[Change, ...], ...]  # those that can start now, then one more away, ...
    apart: tuple[Change, ...]  # those that can't be ordered until the problems are fixed
    problems: tuple[Problem, ...]
    pending: Mapping[str, tuple[str, ...]]  # the undelivered changes' file names, by name
    delivered: Mapping[str, int]  # how many delivered changes have each name
    archived: tuple[str, ...] = ()  # the delivered changes' file names, as archived

    @property
    def pages(self) -> dict[str, str]:
        """The file name each change's page is found by, by change name: a delivered one's is
        its name before the archive stamp. A name that more than one change has has none."""
        found: dict[str, str] = {}
        for name, files in self.pending.items():
            if len(files) == 1 and not self.delivered.get(name):
                found[name] = files[0]
        for file in self.archived:
            name = name_of(file)
            if name not in self.pending and self.delivered.get(name) == 1:
                stamp = requirements.ARCHIVE_STAMP.match(file)
                found[name] = file[stamp.end() :] if stamp else file
        return found

    def change(self, file: str) -> Change | None:
        return next((change for change in self.changes if change.file == file), None)

    def delivered_change(self, file: str, text: str) -> Change:
        """A delivered change, by its file name and text, with what it needs matched as things
        stand now. A `depends-on` that can't be read lists nothing."""
        name = name_of(file)
        try:
            declared = depends_on(text)
        except Unreadable:
            declared = ()
        needs = tuple(_match(need, name, self.pending, self.delivered)[0] for need in declared)
        return Change(file, name, needs, delivered=True)

    def blocks(self, change: Change) -> tuple[Change, ...]:
        """The undelivered changes that need `change`."""

        def matches(need: Need) -> bool:
            if change.delivered:
                return need.delivered and need.name == change.name
            return need.file == change.file

        return tuple(other for other in self.changes if any(map(matches, other.needs)))

    def problems_of(self, change: Change) -> tuple[Problem, ...]:
        return tuple(problem for problem in self.problems if change.name in problem.names)


@dataclass(frozen=True)
class Entry:
    """A row of a repository's requirements list."""

    requirement: Requirement
    detail: Detail | None  # None when its file can't be read inside the checkout
    waits_on: tuple[Need, ...] = ()


@dataclass(frozen=True)
class Listing:
    """A repository's requirements, grouped by what they wait on."""

    levels: tuple[tuple[Entry, ...], ...]  # can start now, then one more away, ...
    apart: tuple[Entry, ...]  # held up by a problem
    problems: tuple[Problem, ...]
    pages: Mapping[str, str]  # the file name each change's page is found by, by change name

    @property
    def entries(self) -> tuple[Entry, ...]:
        return (*(e for level in self.levels for e in level), *self.apart)


def name_of(file_name: str) -> str:
    """A change's name: its file name without `.md`, any archive stamp and any `req-<id>-`."""
    name = file_name.removesuffix(".md")
    if stamp := requirements.ARCHIVE_STAMP.match(name):
        name = name[stamp.end() :]
    if prefix := ID_PREFIX.match(name):
        name = name[prefix.end() :]
    return name


def depends_on(text: str) -> tuple[str, ...]:
    """The names listed under `depends-on:` in a change's front matter, which starts on its
    first line. Raises Unreadable when they can't be read."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if lines[0] != "---":
        return ()
    names: list[str] = []
    listing = seen = False
    for line in lines[1:]:
        if line == "---":
            return tuple(dict.fromkeys(names))
        if listing:
            indented = line.lstrip(" \t")
            if not indented or indented.startswith("#"):
                continue
            if item := LIST_ITEM.fullmatch(line):
                names.append(item[1])
                continue
            # Only the next key, unindented, ends the list.
            if line != indented or line.startswith("-") or ":" not in line:
                raise Unreadable(f'has a line under depends-on that is not "- <name>": "{line}"')
            listing = False
        if LIST_START.fullmatch(line):
            if seen:
                raise Unreadable("has depends-on twice")
            seen = listing = True
        elif line.startswith("depends-on:"):
            raise Unreadable(
                'lists its depends-on on one line; put each name on a line of its own, after "- "'
            )
    raise Unreadable("its front matter has no closing ---")


def order(todo: Mapping[str, str | None], archived: Iterable[str]) -> Backlog:
    """Order the changes in `todo`, each file name's text (None when it isn't read), by what each
    needs. `archived` holds the file names of the delivered changes."""
    files = sorted(todo)
    names = {file: name_of(file) for file in files}
    pending: dict[str, tuple[str, ...]] = {}
    for file in files:
        pending[names[file]] = (*pending.get(names[file], ()), file)
    delivered = Counter(name_of(file) for file in archived)
    problems: list[Problem] = []
    stuck: set[str] = set()  # files with a problem of their own

    declared: dict[str, tuple[str, ...]] = {}
    for file in files:
        try:
            text = todo[file]
            if text is None:
                raise Unreadable(UNREAD)
            declared[file] = depends_on(text)
        except Unreadable as exc:
            problems.append(Problem((names[file],), str(exc)))
            stuck.add(file)
            declared[file] = ()

    changes: list[Change] = []
    edges: dict[str, list[str]] = {}
    for file in files:
        needs = []
        for name in declared[file]:
            need, wrong = _match(name, names[file], pending, delivered)
            if wrong is not None:
                problems.append(Problem((names[file],), wrong))
                stuck.add(file)
            needs.append(need)
        edges[file] = [need.file for need in needs if need.file is not None]
        changes.append(Change(file, names[file], tuple(needs)))

    reach = {file: _reachable(file, edges) for file in files}
    in_cycles: set[str] = set()
    for file in files:
        if file in reach[file] and file not in in_cycles:
            cycle = [other for other in files if other in reach[file] and file in reach[other]]
            in_cycles.update(cycle)
            problems.append(
                Problem(tuple(names[other] for other in cycle), "depend on one another in a cycle")
            )
    stuck |= in_cycles
    apart = {file for file in files if file in stuck or reach[file] & stuck}

    depth: dict[str, int] = {}
    for file in files:
        if file not in apart:
            _depth(file, edges, depth)
    by_file = {change.file: change for change in changes}
    levels: list[list[Change]] = [[] for _ in range(max(depth.values(), default=-1) + 1)]
    for file in files:
        if file in depth:
            levels[depth[file]].append(by_file[file])
    return Backlog(
        tuple(changes),
        tuple(tuple(level) for level in levels),
        tuple(by_file[file] for file in files if file in apart),
        tuple(problems),
        pending,
        delivered,
        tuple(sorted(archived)),
    )


def of(settings: Settings, repository: Repository) -> Backlog:
    """The repository's backlog, read from its requirements folder and the archive beside it."""
    todo, archived = requirements.change_files(settings, repository)
    return order(todo, archived)


def listing(settings: Settings, repository: Repository) -> Listing:
    """Every requirement in the repository's requirements folder, grouped by what it waits on.
    Each group is by file name."""
    in_folder = {r.file_name: r for r in requirements.in_folder(settings, repository)}
    ordered = of(settings, repository)

    def entries(changes: Iterable[Change]) -> tuple[Entry, ...]:
        found = []
        for change in changes:
            if requirement := in_folder.get(change.file):
                found.append(_entry(settings, repository, requirement, change.waits_on))
        return tuple(found)

    return Listing(
        tuple(entries(level) for level in ordered.levels),
        entries(ordered.apart),
        ordered.problems,
        ordered.pages,
    )


def _entry(
    settings: Settings,
    repository: Repository,
    requirement: Requirement,
    waits_on: tuple[Need, ...] = (),
) -> Entry:
    try:
        detail = requirements.detail(settings, repository, requirement)
    except RequirementError:
        detail = None
    return Entry(requirement, detail, waits_on)


def _match(
    name: str, own: str, pending: Mapping[str, tuple[str, ...]], delivered: Mapping[str, int]
) -> tuple[Need, str | None]:
    """What `name`, needed by the change called `own`, matches, and the problem if it can't."""
    matches = pending.get(name, ())
    count = len(matches) + delivered.get(name, 0)
    if name == own:
        wrong = "needs itself"
    elif count == 0:
        wrong = f'needs "{name}", which matches no change'
    elif count > 1:
        wrong = f'needs "{name}", which matches more than one change'
    else:
        return Need(name, matches[0] if matches else None, not matches), None
    return Need(name, None, False), wrong


def _reachable(start: str, edges: Mapping[str, list[str]]) -> set[str]:
    """Every change `start` needs, directly or through others."""
    seen: set[str] = set()
    stack = list(edges[start])
    while stack:
        file = stack.pop()
        if file not in seen:
            seen.add(file)
            stack.extend(edges[file])
    return seen


def _depth(file: str, edges: Mapping[str, list[str]], depth: dict[str, int]) -> int:
    """The length of the longest chain of undelivered changes `file` waits on."""
    if file not in depth:
        depth[file] = max((_depth(other, edges, depth) + 1 for other in edges[file]), default=0)
    return depth[file]
