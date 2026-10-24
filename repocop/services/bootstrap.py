"""The repo template, and how a repository's branch compares with it.

A sync plan (ADR-006) compares the template's files, rendered, with what a repository has
committed on a branch, with a diff for each difference. The one placeholder, `{{ repo_name }}`,
is replaced in text files. A `.gitkeep` only keeps an empty folder in the template, and isn't
part of it. How a file that exists compares depends on its kind (ADR-021), which the template's
`template.toml` declares:

- managed (the default): identical, or differs and can be overwritten;
- starter: the repository's own once it exists, never offered again;
- merged (JSON): identical when it has every template entry and value, else it is behind the
  template, and a merge brings it up to date while keeping what only the repository has.

A managed file carries a marker on its first line after any shebang or front matter, so a file
the template no longer ships can be told from the repository's own (ADR-032). The branch's
marked files the template doesn't ship are removed from the template, and can be deleted; a file
without the marker never is, whatever its path.

The manifest describes the template, so it is never copied or listed. A plan reads the branch
with two git calls, however many files the template or the branch has, so it is cheap enough
for every page load.
"""

from __future__ import annotations

import difflib
import json
import os
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from repocop.errors import RepoCopError
from repocop.services import git

PLACEHOLDER = "{{ repo_name }}"
KEEP_FILE = ".gitkeep"
MANIFEST = "template.toml"
# A managed file's marker, in Markdown and in files whose comments start with `#`.
MARKDOWN_MARKER = "<!-- managed by template -->"
COMMENT_MARKER = "# managed by template"


class BootstrapError(RepoCopError):
    """The template can't be applied to this checkout."""


class MergeError(BootstrapError):
    """A repository's file the template's entries can't be merged into."""


class NoCommitsError(BootstrapError):
    """The repository has no commits yet, so there is nothing to compare with the template."""


class Kind(StrEnum):
    MANAGED = "managed"
    STARTER = "starter"
    MERGED = "merged"


class FileState(StrEnum):
    MISSING = "missing"
    IDENTICAL = "identical"
    DIFFERS = "differs"
    BEHIND = "behind the template"
    OWNED = "the repository's own"
    UNMERGEABLE = "can't merge"
    RETIRED = "removed from the template"


@dataclass(frozen=True)
class SyncFile:
    path: str
    state: FileState
    diff: str = ""  # the branch's version against what syncing would leave there
    reason: str = ""  # why a merged file can't be merged

    @property
    def up_to_date(self) -> bool:
        return self.state in (FileState.IDENTICAL, FileState.OWNED)


@dataclass(frozen=True)
class SyncPlan:
    ref: str
    files: tuple[SyncFile, ...]

    @property
    def missing(self) -> tuple[SyncFile, ...]:
        return tuple(f for f in self.files if f.state is FileState.MISSING)

    @property
    def differing(self) -> tuple[SyncFile, ...]:
        return tuple(f for f in self.files if f.state is FileState.DIFFERS)

    @property
    def behind(self) -> tuple[SyncFile, ...]:
        return tuple(f for f in self.files if f.state is FileState.BEHIND)

    @property
    def retired(self) -> tuple[SyncFile, ...]:
        return tuple(f for f in self.files if f.state is FileState.RETIRED)

    @property
    def up_to_date(self) -> bool:
        return all(f.up_to_date for f in self.files)


def kinds(template_dir: Path) -> dict[str, Kind]:
    """Each template file's kind, as the template's manifest declares it; managed if it doesn't."""
    return dict(_template_files(template_dir))


def has_marker(data: bytes) -> bool:
    """Whether a file's first line after any shebang or front matter is a managed file's
    marker. Line endings don't matter, so a file committed with CRLF is still managed."""
    lines = [line.removesuffix("\r") for line in data.decode("utf-8", "replace").split("\n")]
    at = 0
    if lines[0].startswith("#!"):
        at = 1
    elif lines[0] == "---":  # front matter ends at the next such line
        at = next((n + 1 for n in range(1, len(lines)) if lines[n] == "---"), len(lines))
    return at < len(lines) and lines[at] in (MARKDOWN_MARKER, COMMENT_MARKER)


def sync_plan(template_dir: Path, checkout: Path, ref: str, repo_name: str) -> SyncPlan:
    """How each template file, rendered for `repo_name`, compares with `ref` in the checkout,
    and which of the branch's marked files the template no longer ships, in path order.

    Refused with NoCommitsError when the checkout has no commits yet.
    """
    files = _template_files(template_dir)
    shipped = [path for path, _ in files]
    try:
        found = git.files_containing(checkout, ref, [MARKDOWN_MARKER, COMMENT_MARKER])
        unshipped = sorted(set(found) - set(shipped))
        committed = git.read_files(checkout, ref, [*shipped, *unshipped])
    except git.GitError as exc:
        if not git.has_commits(checkout):
            raise NoCommitsError(
                f"{repo_name} has no commits yet. Make a first commit on {ref}, so the "
                "template can be synced with it."
            ) from None
        raise BootstrapError(str(exc)) from exc
    compared = [
        _compare(template_dir, path, kind, committed[path], repo_name) for path, kind in files
    ]
    retired = [
        SyncFile(path, FileState.RETIRED, _diff(path, data, b""))
        for path in unshipped
        if (data := committed[path]) is not None and has_marker(data)
    ]
    return SyncPlan(ref, tuple(sorted(compared + retired, key=lambda file: file.path)))


def merge(template_dir: Path, path: str, repo_name: str, current: bytes) -> bytes:
    """`current`, a JSON object, brought up to date with the template, which wins (ADR-027).

    Keys only the template has are added after the repository's, and array items it lacks are
    appended, both in template order. Keys and array items only the repository has stay where
    they are. Wherever both have a value that isn't an object or array on both sides, the
    template's replaces the repository's. The result is two-space JSON with a trailing newline;
    `current` comes back unchanged when it already has everything the template says.
    """
    try:
        ours = json.loads(current.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MergeError(f"not valid JSON ({exc})") from exc
    if not isinstance(ours, dict):
        raise MergeError("not a JSON object")
    merged = _merge_json(ours, json.loads(rendered(template_dir, path, repo_name)))
    if _canonical(merged) == _canonical(ours):  # as JSON, where true and 1 differ
        return current
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def rendered(template_dir: Path, path: str, repo_name: str) -> bytes:
    """A template file's bytes as they would be written for `repo_name`."""
    return _render((template_dir / path).read_bytes(), repo_name)


def _template_files(template_dir: Path) -> list[tuple[str, Kind]]:
    """(relative path, kind) for every template file, in path order."""
    if not template_dir.is_dir():
        raise BootstrapError(f"the template directory {template_dir} doesn't exist")
    paths = []
    for dirpath, _, filenames in os.walk(template_dir):
        folder = Path(dirpath).relative_to(template_dir)
        for filename in filenames:
            path = (folder / filename).as_posix()
            if filename != KEEP_FILE and path != MANIFEST:
                paths.append(path)
    declared = _manifest(template_dir, set(paths))
    return sorted((path, declared.get(path, Kind.MANAGED)) for path in paths)


def _manifest(template_dir: Path, files: set[str]) -> dict[str, Kind]:
    """The kinds the template's manifest declares, checked against its `files`."""
    manifest = template_dir / MANIFEST
    if not manifest.is_file():
        return {}
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapError(f"the template's {MANIFEST} isn't valid TOML: {exc}") from exc
    unknown = sorted(set(data) - {Kind.STARTER, Kind.MERGED})
    if unknown:
        raise BootstrapError(f"the template's {MANIFEST} has an unknown key: {', '.join(unknown)}")
    declared: dict[str, Kind] = {}
    for kind in (Kind.STARTER, Kind.MERGED):
        paths = data.get(kind, [])
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise BootstrapError(f"{kind} in the template's {MANIFEST} must be a list of paths")
        for path in paths:
            if path not in files:
                raise BootstrapError(
                    f"the template's {MANIFEST} lists {path}, which isn't a file in the template"
                )
            if path in declared:
                raise BootstrapError(f"the template's {MANIFEST} lists {path} more than once")
            if kind is Kind.MERGED:
                _check_json_object(template_dir, path)
            declared[path] = kind
    return declared


def _check_json_object(template_dir: Path, path: str) -> None:
    """Refuse a merged template file that isn't a JSON object."""
    try:
        data = json.loads((template_dir / path).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise BootstrapError(f"the template's {path} is merged, so it must be a JSON object")


def _compare(
    template_dir: Path, path: str, kind: Kind, committed: bytes | None, repo_name: str
) -> SyncFile:
    """How the template's `path` compares with the branch's version, `committed`."""
    if committed is None:
        return SyncFile(path, FileState.MISSING)
    if kind is Kind.STARTER:
        return SyncFile(path, FileState.OWNED)
    if kind is Kind.MERGED:
        try:
            merged = merge(template_dir, path, repo_name, committed)
        except MergeError as exc:
            return SyncFile(path, FileState.UNMERGEABLE, reason=str(exc))
        if merged == committed:
            return SyncFile(path, FileState.IDENTICAL)
        return SyncFile(path, FileState.BEHIND, _diff(path, committed, merged))
    template = rendered(template_dir, path, repo_name)
    if committed == template:
        return SyncFile(path, FileState.IDENTICAL)
    return SyncFile(path, FileState.DIFFERS, _diff(path, committed, template))


def _merge_json(ours: object, template: object) -> object:
    """`ours` brought up to date with `template`; the rules are in `merge`."""
    if isinstance(ours, dict) and isinstance(template, dict):
        merged = {
            key: _merge_json(value, template[key]) if key in template else value
            for key, value in ours.items()
        }
        merged.update((key, value) for key, value in template.items() if key not in ours)
        return merged
    if isinstance(ours, list) and isinstance(template, list):
        items = list(ours)
        present = {_canonical(item) for item in ours}
        for item in template:
            if _canonical(item) not in present:
                items.append(item)
                present.add(_canonical(item))
        return items
    return template


def _canonical(value: object) -> str:
    """A JSON value's identity, telling apart what Python equates (`true` and `1`)."""
    return json.dumps(value, sort_keys=True)


def _diff(path: str, committed: bytes, template: bytes) -> str:
    try:
        before, after = committed.decode("utf-8"), template.decode("utf-8")
    except UnicodeDecodeError:
        return "Binary files differ"
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)


def _render(data: bytes, repo_name: str) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return text.replace(PLACEHOLDER, repo_name).encode("utf-8")
