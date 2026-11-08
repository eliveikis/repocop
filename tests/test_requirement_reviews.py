"""Requirement reviews: whether a requirement is ready to implement, by the review its review
workflow saved, on its board card and its page, and what is never read."""

import hashlib
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import PROJECT_ROOT, Settings
from repocop.services.requirement_reviews import Readiness, Review, Standing, Verdict, readiness
from tests.conftest import NOW, add_requirement, record_session, run_git

SKILL = PROJECT_ROOT / "templates" / "default-repo" / ".claude" / "skills" / "review-requirement"
REQUIREMENT = "specs/changes/todo/bulk-import.md"
PAGE = "/repositories/1/requirements/bulk-import.md"
TEXT = b"Import in bulk.\n"
SAVED_AT = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def a_review(verdict: Verdict = Verdict.YES, text: bytes = TEXT) -> Review:
    return Review(REQUIREMENT, verdict, 0, hashlib.sha256(text).hexdigest(), SAVED_AT, "Fine.\n")


@pytest.mark.parametrize(
    ("review", "started", "text", "standing"),
    [
        (None, None, TEXT, Standing.NOT_REVIEWED),
        (None, SAVED_AT, TEXT, Standing.UNFINISHED),
        (a_review(), SAVED_AT + timedelta(seconds=1), TEXT, Standing.UNFINISHED),
        (a_review(), SAVED_AT - timedelta(minutes=5), TEXT, Standing.READY),
        (a_review(), None, TEXT, Standing.READY),
        (a_review(Verdict.WITH_ASSUMPTIONS), None, TEXT, Standing.WITH_ASSUMPTIONS),
        (a_review(Verdict.NO), None, TEXT, Standing.NOT_READY),
        (a_review(), None, b"Import in bulk, faster.\n", Standing.CHANGED),
        (a_review(Verdict.NO), None, b"Answered.\n", Standing.CHANGED),
        (a_review(Verdict.NO), None, None, Standing.NOT_READY),  # the file can't be read
    ],
)
def test_readiness_is_the_latest_reviews_verdict_on_the_text_it_reviewed(
    review: Review | None, started: datetime | None, text: bytes | None, standing: Standing
) -> None:
    assert readiness(review, started, text) == Readiness(standing, review, started)


# ---------------------------------------------------------------- pages


@pytest.fixture
def checkout(client: TestClient, settings: Settings, remote_repo: Path) -> Path:
    """The registered repository's checkout, with the template's review skill and a requirement."""
    response = client.post(
        "/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"}
    )
    assert response.status_code == 200, response.text
    checkout = settings.repos_root / "sample"
    shutil.copytree(SKILL, checkout / ".claude" / "skills" / "review-requirement")
    run_git("add", ".claude", cwd=checkout)
    run_git("commit", "-qm", "Add the skill", cwd=checkout)
    add_requirement(checkout, "bulk-import.md", TEXT.decode())
    return checkout


def save_review(
    checkout: Path, verdict: str, blocking: int, report: str, *, ago: float | None = None
) -> None:
    """Save a review as the review workflow does, with the template's own script: `ago`
    minutes before NOW, when given, or else now."""
    result = subprocess.run(
        [
            checkout / ".claude/skills/review-requirement/save-review.sh",
            REQUIREMENT,
            verdict,
            str(blocking),
        ],
        cwd=checkout,
        input=report,
        capture_output=True,
        text=True,
        check=True,
    )
    if ago is not None:
        saved = Path(result.stdout.strip())
        at = (NOW - timedelta(minutes=ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        saved.write_text(re.sub(r"(?m)^at: .*$", f"at: {at}", saved.read_text(), count=1))


def card_status(client: TestClient, stage: str = "to-do") -> str:
    """The readiness on the requirement's card in the `stage` column of the repository's board."""
    html = client.get("/repositories/1").text
    column = re.search(rf'data-stage="{stage}".*?</section>', html, re.S)
    assert column, f"no {stage} column"
    status = re.search(r'class="status readiness status-([a-z-]+)">([^<]*)</span>', column[0])
    assert status, f"no readiness on a card in {stage}"
    return f"{status[1]}: {status[2]}"


def review_section(client: TestClient) -> str:
    html = client.get(PAGE).text
    match = re.search(r'<section id="review".*?</section>', html, re.S)
    assert match, "no review section"
    return match[0]


def test_a_requirement_no_review_has_saved_is_not_reviewed(
    client: TestClient, checkout: Path
) -> None:
    assert card_status(client) == "not-reviewed: Not reviewed"
    assert "No review has saved its result yet" in review_section(client)


def test_a_saved_review_shows_its_verdict_and_its_text_escaped(
    client: TestClient, checkout: Path
) -> None:
    save_review(checkout, "no", 2, "## Summary\nNo: <b>two</b> questions block it.\n")
    assert card_status(client) == "not-ready: Not ready · 2 questions"
    section = review_section(client)
    assert "says <code>no</code> with 2 blocking questions" in section
    assert "No: &lt;b&gt;two&lt;/b&gt; questions block it." in section


def test_a_requirement_edited_since_its_review_says_so_until_it_is_reviewed_again(
    client: TestClient, checkout: Path
) -> None:
    save_review(checkout, "no", 1, "Answer the question.\n")
    (checkout / REQUIREMENT).write_text("Import in bulk, from CSV.\n")  # answered, uncommitted
    assert card_status(client) == "changed-since-review: Changed since review"
    assert "of an earlier text of the file" in review_section(client)
    save_review(checkout, "yes", 0, "Ready.\n")
    assert card_status(client) == "ready: Ready"


def test_a_review_started_after_the_last_one_saved_is_unfinished_until_it_saves(
    client: TestClient, checkout: Path
) -> None:
    save_review(checkout, "yes-with-assumptions", 0, "Ready, assuming CSV.\n", ago=30)
    assert card_status(client) == "ready-with-assumptions: Ready with assumptions"
    run = {
        "event": "workflow",
        "ago": 10,
        "workflow": "review-requirement",
        "argument": REQUIREMENT,
    }
    record_session(checkout, run)  # its session works on it, so its card is in progress
    assert card_status(client, "in-progress") == "review-unfinished: Review unfinished"
    assert "has saved no result" in review_section(client)
    record_session(checkout, {"event": "closed", "ago": 5})  # stopped before it saved
    assert card_status(client) == "review-unfinished: Review unfinished"
    save_review(checkout, "yes", 0, "Ready.\n")
    assert card_status(client) == "ready: Ready"


def test_a_review_saved_through_a_link_or_for_another_file_is_never_read(
    client: TestClient, checkout: Path, tmp_path: Path
) -> None:
    save_review(checkout, "yes", 0, "Ready.\n")
    reviews = checkout / ".git" / "repocop" / "reviews"
    saved = reviews / "bulk-import.md"
    elsewhere = tmp_path / "elsewhere.md"
    shutil.move(saved, elsewhere)
    saved.symlink_to(elsewhere)
    assert card_status(client) == "not-reviewed: Not reviewed"
    saved.unlink()
    elsewhere.write_text(elsewhere.read_text().replace(REQUIREMENT, "specs/other/bulk-import.md"))
    shutil.copy(elsewhere, saved)
    assert card_status(client) == "not-reviewed: Not reviewed"
    shutil.rmtree(reviews)
    elsewhere.write_text(elsewhere.read_text().replace("specs/other/", "specs/changes/todo/"))
    (tmp_path / "folder").mkdir()
    shutil.copy(elsewhere, tmp_path / "folder" / "bulk-import.md")
    reviews.symlink_to(tmp_path / "folder")
    assert card_status(client) == "not-reviewed: Not reviewed"
