"""The specs conventions in `.claude/rules/specs.md` that can be checked mechanically."""

import re
import subprocess
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT

SPECS = PROJECT_ROOT / "specs"
DECISIONS = SPECS / "decisions"
ARCHIVED_RECORDS = DECISIONS / "archive"
ARCHIVE = SPECS / "changes" / "archive"
ARCHITECTURE = (
    SPECS / "architecture.md",
    PROJECT_ROOT / "templates/default-repo/specs/architecture.md",
)
TEXT = {".md", ".py", ".toml", ".json", ".sh", ".html", ".css", ".yaml", ".yml"}
INDEXES = (SPECS / "index.md", PROJECT_ROOT / "templates/default-repo/specs/index.md")
ADR_ID = re.compile(r"\bADR-(\d{3})\b")
RECORD_NAME = re.compile(r"adr-(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
ARCHIVED_CHANGE_LINK = re.compile(r"\]\([^)]*changes/archive/[^)/]+\.md[^)]*\)")
ARCHIVED_RECORD_LINK = re.compile(r"\]\([^)]*decisions/archive/[^)/]+\.md[^)]*\)")
FOLDER_ENTRY_LINK = re.compile(r"\]\((?:\./)?(?:changes|decisions)/[^)]*\.md[^)]*\)")
SECTION_LINK = re.compile(r"\]\(([^()\s#:]+\.md)#([^()\s]+)\)")
HEADING = re.compile(r"#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*")
FENCE = re.compile(r"[ \t]*(```|~~~)")


def text_files(root: Path) -> list[Path]:
    """Every text file under `root` that git tracks or would, apart from archived changes.

    What git ignores, such as saved reviews and Claude Code's worktrees, is a host's own."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.split("\0")
    paths = (root / name for name in listed if Path(name).suffix in TEXT)
    return [path for path in paths if path.is_file() and ARCHIVE not in path.parents]


def anchors(markdown: Path) -> set[str]:
    """The anchor GitHub gives each heading of `markdown`, outside fenced code: lower case, without
    punctuation, spaces as hyphens, and a repeated one numbered."""
    found: set[str] = set()
    fenced = False
    for line in markdown.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and (heading := HEADING.fullmatch(line)):
            text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading[1]).lower()
            slug = re.sub(r"[^\w\- ]", "", text).replace(" ", "-")
            anchor, n = slug, 0
            while anchor in found:
                n += 1
                anchor = f"{slug}-{n}"
            found.add(anchor)
    return found


def records() -> list[Path]:
    """The decision records, kept and archived."""
    return sorted(
        path
        for folder in (DECISIONS, ARCHIVED_RECORDS)
        if folder.is_dir()
        for path in folder.iterdir()
        if path.is_file() and path.name != ".gitkeep"
    )


def recorded(folder: Path) -> set[str]:
    """The ids of the well-named records in `folder`."""
    return {
        name[1]
        for path in records()
        if path.parent == folder and (name := RECORD_NAME.fullmatch(path.name))
    }


@pytest.mark.parametrize(
    "architecture", ARCHITECTURE, ids=lambda path: str(path.parent.parent.name)
)
def test_architecture_keeps_no_decisions_log(architecture: Path) -> None:
    text = architecture.read_text(encoding="utf-8")
    assert not re.search(r"^#+ .*decision", text, re.IGNORECASE | re.MULTILINE)
    assert not ADR_ID.search(text)


def test_decision_records_are_named_and_titled_by_their_id() -> None:
    numbers = []
    for path in records():
        name = RECORD_NAME.fullmatch(path.name)
        assert name, f"{path.name} isn't named adr-<nnn>-<slug>.md"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith(f"# ADR-{name[1]}: "), path.name
        assert any(line.startswith("**Status:**") for line in lines), path.name
        numbers.append(name[1])
    assert sorted({n for n in numbers if numbers.count(n) > 1}) == []


def test_decision_records_exist_for_every_cited_id() -> None:
    known = recorded(DECISIONS) | recorded(ARCHIVED_RECORDS)
    cited = {
        f"ADR-{number} in {path.relative_to(PROJECT_ROOT)}"
        for path in text_files(PROJECT_ROOT)
        for number in ADR_ID.findall(path.read_text(encoding="utf-8"))
        if number not in known
    }
    assert cited == set()


def test_only_records_and_changes_cite_archived_records() -> None:
    archived = recorded(ARCHIVED_RECORDS)
    citing = {
        f"{citation} in {path.relative_to(PROJECT_ROOT)}"
        for path in text_files(PROJECT_ROOT)
        if DECISIONS not in path.parents and SPECS / "changes" not in path.parents
        for text in [path.read_text(encoding="utf-8")]
        for citation in [
            *(f"ADR-{number}" for number in ADR_ID.findall(text) if number in archived),
            *ARCHIVED_RECORD_LINK.findall(text),
        ]
    }
    assert citing == set()


@pytest.mark.parametrize("index", INDEXES, ids=lambda path: str(path.parent.parent.name))
def test_index_lists_no_changes_or_decision_records(index: Path) -> None:
    assert FOLDER_ENTRY_LINK.findall(index.read_text(encoding="utf-8")) == []


def test_specs_rules_and_skills_never_link_to_archived_changes() -> None:
    governed = [
        path
        for root in (SPECS, PROJECT_ROOT / ".claude", PROJECT_ROOT / "templates/default-repo")
        for path in text_files(root)
        if path.suffix == ".md" and SPECS / "changes" not in path.parents
    ]
    linking = [
        str(path.relative_to(PROJECT_ROOT))
        for path in [*governed, PROJECT_ROOT / "CLAUDE.md"]
        if ARCHIVED_CHANGE_LINK.search(path.read_text(encoding="utf-8"))
    ]
    assert linking == []


def test_links_to_a_section_of_another_file_name_one_of_its_headings() -> None:
    """Outside decision records and archived changes, which stay as they were written."""
    broken = {
        f"{path.relative_to(PROJECT_ROOT)} links to {target}#{anchor}"
        for path in text_files(PROJECT_ROOT)
        if path.suffix == ".md" and DECISIONS not in path.parents
        for target, anchor in SECTION_LINK.findall(path.read_text(encoding="utf-8"))
        for linked in [(path.parent / target).resolve()]
        if not linked.is_file() or anchor not in anchors(linked)
    }
    assert broken == set()


def test_changes_depend_only_on_changes_they_can_follow() -> None:
    """`specs/changes/backlog.sh --check` finds no problem in this repository's changes."""
    checked = subprocess.run(
        [SPECS / "changes" / "backlog.sh", "--check"], capture_output=True, text=True, check=False
    )
    assert (checked.returncode, checked.stderr) == (0, "")
