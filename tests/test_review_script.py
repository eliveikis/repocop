"""The template's `.reviews/review.sh`: a branch's review by Codex, read-only, saved beside it
(with Codex faked)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT
from tests.conftest import run_git
from tests.fakes.fake_codex import FakeCodex

TEMPLATE_REVIEWS = PROJECT_ROOT / "templates" / "default-repo" / ".reviews"


@pytest.fixture
def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCodex:
    """Stands in for the Codex CLI: its reviews find nothing (tests/fakes)."""
    directory = tmp_path / "codex"
    directory.mkdir()
    monkeypatch.setenv("FAKE_CODEX_DIR", str(directory))
    return FakeCodex(directory)


@pytest.fixture
def checkout(primary_checkout: Path) -> Path:
    """A clone with the template's `.reviews/`, on a branch with one commit `origin/main` lacks."""
    shutil.copytree(TEMPLATE_REVIEWS, primary_checkout / ".reviews")
    run_git("add", ".reviews", cwd=primary_checkout)
    run_git("commit", "-qm", "Add the reviews folder", cwd=primary_checkout)
    run_git("push", "-q", "origin", "main", cwd=primary_checkout)
    run_git("switch", "-qc", "feature/req-1-import", cwd=primary_checkout)
    (primary_checkout / "import.py").write_text("print('import')\n")
    run_git("add", "import.py", cwd=primary_checkout)
    run_git("commit", "-qm", "Add import", cwd=primary_checkout)
    return primary_checkout


def review(
    checkout: Path, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [checkout / ".reviews" / "review.sh", *args],
        cwd=cwd or checkout,
        env={**os.environ, **(env or {})},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def saved(checkout: Path) -> list[str]:
    return sorted(p.name for p in (checkout / ".reviews").iterdir() if p.suffix == ".md")


def test_review_saves_codexs_review_in_the_ignored_folder_and_prints_it(
    checkout: Path, fake_codex: FakeCodex
) -> None:
    fake_codex.review_says("- [P2] Close the file")
    result = review(checkout)
    assert result.returncode == 0, result.stderr
    short = run_git("rev-parse", "--short", "HEAD", cwd=checkout)
    name = f"feature-req-1-import-{short}.md"
    assert saved(checkout) == [name]
    assert (checkout / ".reviews" / name).read_text() == "- [P2] Close the file\n"
    assert "- [P2] Close the file" in result.stdout and f".reviews/{name}" in result.stdout
    assert run_git("check-ignore", f".reviews/{name}", cwd=checkout) == f".reviews/{name}"
    assert run_git("status", "--porcelain", cwd=checkout) == ""


def test_review_runs_codex_read_only_with_no_approvals(
    checkout: Path, fake_codex: FakeCodex
) -> None:
    review(checkout)
    (call,) = fake_codex.reviews
    assert call["args"] == [
        "review",
        "--base=origin/main",
        "-c",
        'sandbox_mode="read-only"',
        "-c",
        'approval_policy="never"',
        "-c",
        'model_reasoning_effort="high"',
    ]
    assert call["cwd"] == str(checkout) and call["input_closed"] is True


def test_review_takes_another_base_effort_and_model(checkout: Path, fake_codex: FakeCodex) -> None:
    review(checkout, "main", env={"REVIEW_EFFORT": "xhigh", "REVIEW_MODEL": "gpt-6-sol"})
    review(checkout, env={"REVIEW_EFFORT": ""})
    named, blank = (call["args"] for call in fake_codex.reviews)
    assert "--base=main" in named
    assert 'model_reasoning_effort="xhigh"' in named and 'review_model="gpt-6-sol"' in named
    assert not any("model_reasoning_effort" in arg for arg in blank)


def test_review_runs_from_anywhere_in_the_checkout(checkout: Path, fake_codex: FakeCodex) -> None:
    (checkout / "docs").mkdir()
    result = review(checkout, cwd=checkout / "docs")
    assert result.returncode == 0, result.stderr
    assert fake_codex.reviews[0]["cwd"] == str(checkout)


def test_review_refuses_a_base_that_is_not_there(checkout: Path, fake_codex: FakeCodex) -> None:
    result = review(checkout, "origin/nope")
    assert result.returncode != 0
    assert "origin/nope isn't here" in result.stderr
    assert fake_codex.reviews == [] and saved(checkout) == []


def test_review_refuses_uncommitted_changes(checkout: Path, fake_codex: FakeCodex) -> None:
    (checkout / "draft.txt").write_text("not committed\n")
    result = review(checkout)
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
    assert fake_codex.reviews == []


def test_a_saved_review_does_not_count_as_an_uncommitted_change(
    checkout: Path, fake_codex: FakeCodex
) -> None:
    assert review(checkout).returncode == 0
    second = review(checkout)
    assert second.returncode == 0, second.stderr


def test_a_failed_review_saves_nothing(checkout: Path, fake_codex: FakeCodex) -> None:
    fake_codex.fail_with("out of credit")
    result = review(checkout)
    assert result.returncode != 0
    assert "ERROR: out of credit" in result.stderr
    assert saved(checkout) == []


def test_review_refuses_the_bases_own_branch(checkout: Path, fake_codex: FakeCodex) -> None:
    run_git("switch", "-q", "main", cwd=checkout)
    result = review(checkout)
    assert result.returncode != 0
    assert "origin/main's own branch" in result.stderr
    assert fake_codex.reviews == [] and saved(checkout) == []


def test_review_refuses_a_branch_with_nothing_the_base_lacks(
    checkout: Path, fake_codex: FakeCodex
) -> None:
    run_git("switch", "-q", "-c", "empty", "origin/main", cwd=checkout)
    result = review(checkout)
    assert result.returncode != 0
    assert "no commits origin/main lacks" in result.stderr
    assert fake_codex.reviews == []


def test_review_refuses_without_codex_signed_in(checkout: Path, fake_codex: FakeCodex) -> None:
    fake_codex.log_out()
    result = review(checkout)
    assert result.returncode != 0
    assert "isn't signed in: run codex login" in result.stderr
    assert fake_codex.reviews == [] and saved(checkout) == []


def test_review_refuses_without_codex_installed(checkout: Path, tmp_path: Path) -> None:
    tools = tmp_path / "no-codex"
    tools.mkdir()
    for tool in ("git", "sh", "mktemp", "tr", "cat", "mv", "rm"):
        (tools / tool).symlink_to(shutil.which(tool) or tool)
    result = review(checkout, env={"PATH": str(tools)})
    assert result.returncode != 0
    assert "Codex isn't installed" in result.stderr
    assert saved(checkout) == []
