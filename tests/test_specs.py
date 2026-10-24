"""The specs conventions in `.claude/rules/specs.md` that can be checked mechanically."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT

SPECS = PROJECT_ROOT / "specs"
DECISIONS = SPECS / "decisions"
ARCHIVE = SPECS / "changes" / "archive"
ARCHITECTURE = (
    SPECS / "architecture.md",
    PROJECT_ROOT / "templates/default-repo/specs/architecture.md",
)
SKIPPED = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
TEXT = {".md", ".py", ".toml", ".json", ".sh", ".html", ".css", ".yaml", ".yml"}
INDEXES = (SPECS / "index.md", PROJECT_ROOT / "templates/default-repo/specs/index.md")
ADR_ID = re.compile(r"\bADR-(\d{3})\b")
RECORD_NAME = re.compile(r"adr-(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
ARCHIVED_CHANGE_LINK = re.compile(r"\]\([^)]*changes/archive/[^)/]+\.md[^)]*\)")
FOLDER_ENTRY_LINK = re.compile(r"\]\((?:\./)?(?:changes|decisions)/[^)]*\.md[^)]*\)")


def text_files(root: Path) -> list[Path]:
    """Every text file under `root`, apart from tool caches and archived changes."""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIPPED and Path(folder, d) != ARCHIVE]
        found += [Path(folder, name) for name in files if Path(name).suffix in TEXT]
    return found


def records() -> list[Path]:
    return sorted(path for path in DECISIONS.iterdir() if path.name != ".gitkeep")


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
    assert len(numbers) == len(set(numbers))


def test_decision_records_exist_for_every_cited_id() -> None:
    recorded = {RECORD_NAME.fullmatch(path.name)[1] for path in records()}  # type: ignore[index]
    cited = {
        f"ADR-{number} in {path.relative_to(PROJECT_ROOT)}"
        for path in text_files(PROJECT_ROOT)
        for number in ADR_ID.findall(path.read_text(encoding="utf-8"))
        if number not in recorded
    }
    assert cited == set()


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


def test_changes_depend_only_on_changes_they_can_follow() -> None:
    """`specs/changes/backlog.sh --check` finds no problem in this repository's changes."""
    checked = subprocess.run(
        [SPECS / "changes" / "backlog.sh", "--check"], capture_output=True, text=True, check=False
    )
    assert (checked.returncode, checked.stderr) == (0, "")
