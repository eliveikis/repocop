"""The template's `review-requirement/save-review.sh`: a requirement's review saved with its
verdict in the repository's git folder, out of every commit, and what it refuses."""

import hashlib
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT
from tests.conftest import add_requirement, run_git

SKILL = PROJECT_ROOT / "templates" / "default-repo" / ".claude" / "skills" / "review-requirement"
SCRIPT = ".claude/skills/review-requirement/save-review.sh"
REQUIREMENT = "specs/changes/todo/bulk-import.md"
REPORT = "## Summary\nNo: two questions block it.\n"


@pytest.fixture
def checkout(primary_checkout: Path) -> Path:
    """A clone with the template's review-requirement skill and a requirement, committed."""
    shutil.copytree(SKILL, primary_checkout / ".claude" / "skills" / "review-requirement")
    run_git("add", ".claude", cwd=primary_checkout)
    run_git("commit", "-qm", "Add the skill", cwd=primary_checkout)
    add_requirement(primary_checkout, "bulk-import.md", "Import in bulk.\n")
    return primary_checkout


def save(
    checkout: Path, *args: str, report: str = REPORT, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [checkout / SCRIPT, *args],
        cwd=cwd or checkout,
        input=report,
        capture_output=True,
        text=True,
        check=False,
    )


def test_save_review_keeps_the_review_with_its_verdict_out_of_every_commit(
    checkout: Path,
) -> None:
    before = datetime.now(UTC).replace(microsecond=0)
    result = save(checkout, REQUIREMENT, "no", "2")
    assert result.returncode == 0, result.stderr
    saved = checkout / ".git" / "repocop" / "reviews" / "bulk-import.md"
    assert result.stdout.strip() == str(saved)
    header, report = saved.read_text().removeprefix("---\n").split("---\n", 1)
    fields = dict(line.split(": ", 1) for line in header.splitlines())
    assert fields.pop("at") >= before.strftime("%Y-%m-%dT%H:%M:%S")
    assert fields == {
        "v": "1",
        "requirement": REQUIREMENT,
        "verdict": "no",
        "blocking": "2",
        "sha256": hashlib.sha256(b"Import in bulk.\n").hexdigest(),
    }
    assert report == REPORT
    assert run_git("status", "--porcelain", cwd=checkout) == ""


def test_save_review_from_a_worktree_lands_in_the_shared_git_folder_replacing_the_last(
    checkout: Path, tmp_path: Path
) -> None:
    assert save(checkout, REQUIREMENT, "no", "2").returncode == 0
    worktree = tmp_path / "elsewhere"
    run_git("worktree", "add", "-q", "-b", "bulk-import", str(worktree), cwd=checkout)
    result = save(checkout, REQUIREMENT, "yes", "0", report="## Summary\nYes.\n", cwd=worktree)
    assert result.returncode == 0, result.stderr
    reviews = checkout / ".git" / "repocop" / "reviews"
    assert sorted(p.name for p in reviews.iterdir()) == ["bulk-import.md"]
    assert "verdict: yes\n" in (reviews / "bulk-import.md").read_text()


@pytest.mark.parametrize(
    ("args", "says"),
    [
        ((REQUIREMENT, "maybe", "0"), "the verdict is"),
        ((REQUIREMENT, "no", "two"), "a count"),
        ((REQUIREMENT, "no"), "usage"),
        (("/etc/passwd.md", "no", "0"), "relative"),
        (("specs/../specs/changes/todo/bulk-import.md", "no", "0"), "'..'"),
        (("-x.md", "no", "0"), "relative"),
        (("specs/changes/todo/bulk\nimport.md", "no", "0"), "relative"),
        (("specs/changes/todo/bulk\timport.md", "no", "0"), "control"),
        (("specs/changes/todo/bulk-import.txt", "no", "0"), "Markdown"),
    ],
)
def test_save_review_refuses_a_wrong_argument(
    checkout: Path, args: tuple[str, ...], says: str
) -> None:
    result = save(checkout, *args)
    assert result.returncode == 2
    assert says in result.stderr
    assert not (checkout / ".git" / "repocop" / "reviews").exists()


def test_save_review_refuses_a_requirement_that_leads_outside_the_checkout(
    checkout: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("Not the repository's.\n")
    (checkout / "specs" / "elsewhere").symlink_to(outside)
    linked = checkout / "specs" / "changes" / "todo" / "linked.md"
    linked.symlink_to(outside / "secret.md")
    for path in ("specs/elsewhere/secret.md", "specs/changes/todo/linked.md"):
        result = save(checkout, path, "yes", "0")
        assert result.returncode == 1, path
        assert "ERROR" in result.stderr
    assert not (checkout / ".git" / "repocop" / "reviews").exists()


def test_save_review_never_writes_through_a_linked_reviews_folder(
    checkout: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (checkout / ".git" / "repocop").mkdir()
    (checkout / ".git" / "repocop" / "reviews").symlink_to(elsewhere)
    result = save(checkout, REQUIREMENT, "yes", "0")
    assert result.returncode == 1
    assert "is a link" in result.stderr
    assert list(elsewhere.iterdir()) == []


def test_save_review_refuses_an_empty_review_and_keeps_the_last(checkout: Path) -> None:
    assert save(checkout, REQUIREMENT, "no", "2").returncode == 0
    result = save(checkout, REQUIREMENT, "yes", "0", report="")
    assert result.returncode == 1
    assert "no review" in result.stderr
    reviews = checkout / ".git" / "repocop" / "reviews"
    assert sorted(p.name for p in reviews.iterdir()) == ["bulk-import.md"]
    assert "verdict: no\n" in (reviews / "bulk-import.md").read_text()
