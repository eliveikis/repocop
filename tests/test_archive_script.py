"""The complete-change skill's `archive.sh`: a change moved into the archive under a name stamped
with when, and the files that still mention its old path."""

import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT
from tests.conftest import run_git

SCRIPT = PROJECT_ROOT / ".claude" / "skills" / "complete-change" / "archive.sh"
CHANGE = "specs/changes/todo/req-3-bulk-import.md"
STAMPED = re.compile(r"specs/changes/archive/(\d{4}-\d{2}-\d{2}T\d{6}Z)-req-3-bulk-import\.md")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a change in todo/ and an index that links it."""
    root = tmp_path / "repo"
    (root / "specs/changes/todo").mkdir(parents=True)
    (root / "specs/changes/archive").mkdir(parents=True)
    (root / CHANGE).write_text("# Bulk import\n")
    (root / "specs/index.md").write_text("| [req-3](changes/todo/req-3-bulk-import.md) |\n")
    run_git("init", "-q", "-b", "main", cwd=root)
    run_git("add", ".", cwd=root)
    run_git("commit", "-qm", "Add req-3", cwd=root)
    return root


def archive(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SCRIPT, *args], cwd=cwd or repo, capture_output=True, text=True, check=False
    )


def test_archive_moves_the_change_under_a_name_stamped_with_the_utc_time(repo: Path) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    result = archive(repo, CHANGE)
    assert result.returncode == 0, result.stderr
    new_path = result.stdout.splitlines()[0]
    match = STAMPED.fullmatch(new_path)
    assert match, new_path
    stamp = datetime.strptime(match[1], "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
    assert before <= stamp <= datetime.now(UTC) + timedelta(seconds=1)
    assert (repo / new_path).read_text() == "# Bulk import\n" and not (repo / CHANGE).exists()
    assert run_git("status", "--porcelain", cwd=repo) == f"R  {CHANGE} -> {new_path}"


def test_archive_lists_the_files_that_still_mention_the_old_path(repo: Path) -> None:
    result = archive(repo, CHANGE)
    mentions = result.stdout.splitlines()[1:]
    assert mentions == ["specs/index.md:1:| [req-3](changes/todo/req-3-bulk-import.md) |"]


def test_archive_works_from_anywhere_in_the_repository(repo: Path) -> None:
    result = archive(repo, CHANGE, cwd=repo / "specs")
    assert result.returncode == 0, result.stderr
    assert STAMPED.fullmatch(result.stdout.splitlines()[0])


def test_archive_refuses_a_change_that_is_not_committed(repo: Path) -> None:
    draft = "specs/changes/todo/draft.md"
    (repo / draft).write_text("# Draft\n")
    result = archive(repo, draft)
    assert result.returncode != 0 and "isn't committed" in result.stderr
    assert (repo / draft).exists()


def test_archive_refuses_a_path_that_is_not_there(repo: Path) -> None:
    result = archive(repo, "specs/changes/todo/nope.md")
    assert result.returncode != 0 and "isn't a file" in result.stderr


def test_archive_needs_exactly_one_path(repo: Path) -> None:
    result = archive(repo)
    assert result.returncode == 2 and "usage" in result.stderr
