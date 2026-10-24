"""The Review action on a requirement's page, and a review task's page (with Codex faked)."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import run_git
from tests.fakes.fake_claude import FakeClaudeFactory
from tests.fakes.fake_codex import FakeCodex
from tests.fakes.fake_gh import FakeGh

REVIEW_BUTTON = '<button type="submit">Review with Codex</button>'
ADDRESS_BUTTON = '<button type="submit">Address this review</button>'
OPEN_BUTTON = '<button type="submit">Open PR</button>'
COPILOT_BUTTON = '<button type="submit">Request Copilot review</button>'
INSTRUCTION_FORM = '<form class="instruction"'


@pytest.fixture
def requirement(
    client: TestClient, github_checkout: Path, fake_gh: FakeGh, fake_codex: FakeCodex
) -> None:
    """Repository `sample` on github.com with a committed skill, and bulk-user-import created
    in the UI."""
    for name in ("implement", "address-review"):
        folder = github_checkout / ".claude" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=github_checkout)
    run_git("commit", "-qm", "Add skills", cwd=github_checkout)
    client.post("/repositories", data={"remote_url": "", "name": "sample"})
    client.post(
        "/repositories/1/requirements",
        data={"name": "Bulk user import", "kind": "feature", "body": "Import users."},
    )


@pytest.fixture
def branch(client: TestClient, requirement: None) -> None:
    """bulk-user-import after its first task, which is over: it has a branch and a worktree."""
    client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    wait_for_status(client, 1, "waiting_for_user")
    client.post("/tasks/1/done")


def wait_for_status(client: TestClient, task_id: int, status: str) -> str:
    """The task's page, once it shows this status."""
    deadline = time.monotonic() + 10.0
    while True:
        html = client.get(f"/tasks/{task_id}").text
        if f'class="status status-{status}">{status}<' in html:
            return html
        if time.monotonic() > deadline:
            raise AssertionError(f"task #{task_id} never reached {status}")
        time.sleep(0.02)


def worktree(settings: Settings) -> Path:
    return settings.worktrees_root / "sample" / "bulk-user-import"


def start_review(client: TestClient) -> str:
    """Click Review and return the address it goes to."""
    response = client.post(
        "/repositories/1/requirements/bulk-user-import.md/review", follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return str(response.headers["location"])


# ---------------------------------------------------------------- the requirement's page


@pytest.mark.usefixtures("requirement")
def test_a_requirement_without_a_branch_offers_no_review(client: TestClient) -> None:
    assert REVIEW_BUTTON not in client.get("/repositories/1/requirements/bulk-user-import.md").text
    response = client.post("/repositories/1/requirements/bulk-user-import.md/review")
    assert response.status_code == 400
    assert "bulk-user-import has no branch yet" in response.text


@pytest.mark.usefixtures("branch")
def test_a_requirement_with_a_branch_offers_a_review_beside_its_pull_request(
    client: TestClient,
) -> None:
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert REVIEW_BUTTON in html and OPEN_BUTTON in html
    assert html.index(REVIEW_BUTTON) < html.index(OPEN_BUTTON)
    assert "<code>agent/bulk-user-import</code> hasn't been reviewed yet." in html
    assert "against <code>origin/main</code> as last fetched" in html
    assert "never blocks a pull request" in html


@pytest.mark.usefixtures("branch")
def test_review_starts_a_task_that_shows_codexs_output_and_its_review(
    client: TestClient, settings: Settings, fake_codex: FakeCodex
) -> None:
    fake_codex.review_says("- [P2] Close the file <b>please</b>")
    assert start_review(client) == "http://testserver/tasks/2?started=true"
    html = wait_for_status(client, 2, "completed")
    assert "<h1>#2 · Codex review</h1>" in html
    assert "sandbox: read-only" in html
    assert (
        '<span class="who">Codex</span><pre>- [P2] Close the file &lt;b&gt;please&lt;/b&gt;</pre>'
        in html
    )
    assert INSTRUCTION_FORM not in html
    (call,) = fake_codex.reviews
    assert call["cwd"] == str(worktree(settings))


@pytest.mark.usefixtures("branch")
def test_the_page_shows_the_latest_review_and_when_the_branch_has_moved_on(
    client: TestClient, settings: Settings
) -> None:
    reviewed = run_git("rev-parse", "HEAD", cwd=worktree(settings))
    start_review(client)
    wait_for_status(client, 2, "completed")
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert 'Latest review: <a href="http://testserver/tasks/2">#2</a>' in html
    assert f"of <code>{reviewed[:12]}</code>" in html
    assert "The branch has moved on since" not in html
    (worktree(settings) / "more.txt").write_text("more\n")
    run_git("add", "more.txt", cwd=worktree(settings))
    run_git("commit", "-qm", "More", cwd=worktree(settings))
    newer = run_git("rev-parse", "HEAD", cwd=worktree(settings))
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert f"<strong>The branch has moved on since</strong>, to <code>{newer[:12]}</code>." in html
    assert REVIEW_BUTTON in html


@pytest.mark.usefixtures("branch")
def test_review_is_refused_with_the_reason_when_codex_is_signed_out(
    client: TestClient, fake_codex: FakeCodex
) -> None:
    fake_codex.log_out()
    response = client.post("/repositories/1/requirements/bulk-user-import.md/review")
    assert response.status_code == 400
    assert "Codex isn&#39;t signed in: run `codex login`" in response.text
    assert client.get("/tasks/2").status_code == 404
    assert OPEN_BUTTON in response.text  # everything else still works


@pytest.mark.usefixtures("branch")
def test_a_failed_review_says_why_and_never_shows_as_the_latest_review(
    client: TestClient, fake_codex: FakeCodex
) -> None:
    fake_codex.fail_with("out of credit")
    start_review(client)
    html = wait_for_status(client, 2, "failed")
    assert '<dd class="error-text">ERROR: out of credit</dd>' in html
    assert (
        "hasn't been reviewed yet"
        in client.get("/repositories/1/requirements/bulk-user-import.md").text
    )


@pytest.mark.usefixtures("branch")
def test_a_review_with_findings_does_not_stop_the_pull_request_or_copilots_review(
    client: TestClient, fake_codex: FakeCodex
) -> None:
    fake_codex.review_says("- [P1] This is broken")
    start_review(client)
    wait_for_status(client, 2, "completed")
    opened = client.post(
        "/repositories/1/requirements/bulk-user-import.md/pull-request/open", follow_redirects=False
    )
    assert opened.status_code == 303, opened.text
    assert COPILOT_BUTTON in client.get("/repositories/1/requirements/bulk-user-import.md").text


# ---------------------------------------------------------------- addressing a review


@pytest.mark.usefixtures("branch")
def test_address_is_offered_only_once_a_review_has_finished(client: TestClient) -> None:
    assert ADDRESS_BUTTON not in client.get("/repositories/1/requirements/bulk-user-import.md").text
    refused = client.post("/repositories/1/requirements/bulk-user-import.md/review/address")
    assert refused.status_code == 400
    assert "bulk-user-import has no finished review to address" in refused.text
    start_review(client)
    wait_for_status(client, 2, "completed")
    assert ADDRESS_BUTTON in client.get("/repositories/1/requirements/bulk-user-import.md").text


@pytest.mark.usefixtures("branch")
def test_address_starts_a_task_that_is_given_the_review(
    client: TestClient, fake_codex: FakeCodex, fake_claude: FakeClaudeFactory
) -> None:
    fake_codex.review_says("- [P2] Close the file")
    start_review(client)
    wait_for_status(client, 2, "completed")
    response = client.post(
        "/repositories/1/requirements/bulk-user-import.md/review/address", follow_redirects=False
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "http://testserver/tasks/3?started=true"
    html = wait_for_status(client, 3, "waiting_for_user")
    assert "<h1>#3 · address-review</h1>" in html
    assert '<span class="who">You</span><pre>Codex&#39;s review of this branch at commit' in html
    assert "- [P2] Close the file</pre>" in html
    assert INSTRUCTION_FORM in html  # an ordinary task: it takes instructions
    prompt = fake_claude.clients[-1].prompts[0]
    assert prompt.startswith("/address-review specs/changes/todo/bulk-user-import.md\n\n")
    assert prompt.endswith("- [P2] Close the file")


# ---------------------------------------------------------------- a review task's page


@pytest.mark.usefixtures("branch")
def test_a_running_review_takes_no_instruction_and_can_be_cancelled(
    client: TestClient, fake_codex: FakeCodex
) -> None:
    fake_codex.hang()
    start_review(client)
    html = wait_for_status(client, 2, "running")
    assert INSTRUCTION_FORM not in html
    refused = client.post("/tasks/2/instructions", data={"text": "also check the tests"})
    assert refused.status_code == 400
    assert "task #2 is a review, which takes no instructions" in refused.text
    assert client.post("/tasks/2/cancel", follow_redirects=False).status_code == 303
    assert "status-cancelled" in client.get("/tasks/2").text
    assert (
        "hasn't been reviewed yet"
        in client.get("/repositories/1/requirements/bulk-user-import.md").text
    )


@pytest.mark.usefixtures("branch")
def test_a_failed_review_can_be_started_again(client: TestClient, fake_codex: FakeCodex) -> None:
    fake_codex.fail_with("out of credit")
    start_review(client)
    wait_for_status(client, 2, "failed")
    (fake_codex.directory / "fail").unlink()
    again = client.post("/tasks/2/again", follow_redirects=False)
    assert again.headers["location"] == "http://testserver/tasks/3?started=true"
    assert "<h1>#3 · Codex review</h1>" in wait_for_status(client, 3, "completed")


@pytest.mark.usefixtures("branch")
def test_a_claude_tasks_page_still_names_claude_and_takes_instructions(client: TestClient) -> None:
    html = client.get("/tasks/1").text
    assert '<span class="who">Claude</span>' in html
    client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    assert INSTRUCTION_FORM in wait_for_status(client, 2, "waiting_for_user")
