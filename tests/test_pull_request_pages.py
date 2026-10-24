"""Pull request actions on the requirement page and on a completed template sync's page."""

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import run_git
from tests.fakes.fake_gh import FakeGh

BRANCH = "agent/bulk-user-import"
PULL = "https://github.com/owner/sample/pull/1"


def link(url: str) -> str:
    """How a page links a pull request: in a new tab."""
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>'


REQUIREMENT_ACTIONS = (
    "http://testserver/repositories/1/requirements/bulk-user-import.md/pull-request"
)
OPEN_BUTTON = '<button type="submit">Open PR</button>'
OPEN_ANOTHER = '<button type="submit">Open a new PR</button>'
ONLY_LOCAL = "is only on this machine until its pull request is opened"


@pytest.fixture
def requirement(
    client: TestClient, settings: Settings, github_checkout: Path, fake_gh: FakeGh
) -> None:
    """Repository `sample` on github.com with a committed skill, and bulk-user-import created
    in the UI."""
    folder = github_checkout / ".claude" / "skills" / "implement"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# implement\n")
    run_git("add", ".claude", cwd=github_checkout)
    run_git("commit", "-qm", "Add skills", cwd=github_checkout)
    client.post("/repositories", data={"remote_url": "", "name": "sample"})
    client.post(
        "/repositories/1/requirements",
        data={"name": "Bulk user import", "kind": "feature", "body": "Import users."},
    )


def wait_for_status(client: TestClient, task_id: int, status: str) -> None:
    deadline = time.monotonic() + 5.0
    shown = f'class="status status-{status}">{status}<'
    while shown not in client.get(f"/tasks/{task_id}").text.partition("<main")[2]:
        if time.monotonic() > deadline:
            raise AssertionError(f"task #{task_id} never reached {status}")
        time.sleep(0.02)


def run_a_task(client: TestClient, task_id: int = 1) -> None:
    """Start a task on bulk-user-import, let its turn end, and mark it done."""
    client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    wait_for_status(client, task_id, "waiting_for_user")
    client.post(f"/tasks/{task_id}/done")


def sync(client: TestClient) -> str:
    """Apply a template sync and return its task page's address."""
    response = client.post(
        "/repositories/1/sync", data={"create": ["CLAUDE.md"]}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return str(response.headers["location"])


def worktree(settings: Settings, name: str = "bulk-user-import") -> Path:
    return settings.worktrees_root / "sample" / name


def commit_in(folder: Path) -> str:
    (folder / "work.txt").write_text("work\n")
    run_git("add", "work.txt", cwd=folder)
    run_git("commit", "-qm", "Work", cwd=folder)
    return run_git("rev-parse", "HEAD", cwd=folder)


def remote_branches(remote: Path) -> list[str]:
    return run_git("for-each-ref", "--format=%(refname:short)", cwd=remote).splitlines()


# ---------------------------------------------------------------- requirement page


@pytest.mark.usefixtures("requirement")
def test_requirement_page_offers_no_pull_request_before_its_first_task(client: TestClient) -> None:
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert "Pull request" not in html
    assert OPEN_BUTTON not in html


@pytest.mark.usefixtures("requirement")
def test_requirement_page_offers_to_open_a_pull_request_for_its_branch(client: TestClient) -> None:
    run_a_task(client)
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert f"<code>{BRANCH}</code> {ONLY_LOCAL}" in html
    assert f'action="{REQUIREMENT_ACTIONS}/open" target="_blank"' in html  # GitHub in a new tab
    assert OPEN_BUTTON in html
    assert f'action="{REQUIREMENT_ACTIONS}/push"' not in html


@pytest.mark.usefixtures("requirement")
def test_open_pr_from_the_requirement_page_opens_the_pull_request_on_github(
    client: TestClient, remote_repo: Path, fake_gh: FakeGh
) -> None:
    run_a_task(client)
    response = client.post(f"{REQUIREMENT_ACTIONS}/open", follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"] == PULL
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert link(PULL) in html
    assert BRANCH in remote_branches(remote_repo)
    created = fake_gh.calls[-1]
    assert created[created.index("--title") + 1] == "bulk-user-import"
    assert f'action="{REQUIREMENT_ACTIONS}/push"' in html
    assert f'action="{REQUIREMENT_ACTIONS}/review"' in html
    assert OPEN_BUTTON not in html
    assert OPEN_ANOTHER in html
    assert ONLY_LOCAL not in html


@pytest.mark.usefixtures("requirement")
def test_push_from_the_requirement_page_sends_new_commits(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    run_a_task(client)
    client.post(f"{REQUIREMENT_ACTIONS}/open")
    head = commit_in(worktree(settings))
    response = client.post(f"{REQUIREMENT_ACTIONS}/push")
    assert response.status_code == 200, response.text
    assert f"Pushed <code>{BRANCH}</code>." in response.text
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == head


@pytest.mark.usefixtures("requirement")
def test_request_copilot_review_from_the_requirement_page(
    client: TestClient, fake_gh: FakeGh
) -> None:
    run_a_task(client)
    client.post(f"{REQUIREMENT_ACTIONS}/open")
    response = client.post(f"{REQUIREMENT_ACTIONS}/review")
    assert response.status_code == 200, response.text
    assert "Asked Copilot to review the pull request." in response.text
    assert fake_gh.calls[-1] == ["pr", "edit", PULL, "--add-reviewer", "@copilot"]


@pytest.mark.usefixtures("requirement")
def test_a_refused_action_shows_its_reason_on_the_requirement_page(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    run_a_task(client)
    (worktree(settings) / "draft.txt").write_text("not committed\n")
    response = client.post(f"{REQUIREMENT_ACTIONS}/open")
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert "1 file with uncommitted changes" in response.text
    assert OPEN_BUTTON in response.text
    assert remote_branches(remote_repo) == ["main"]


@pytest.mark.usefixtures("requirement")
def test_an_action_during_an_active_task_names_the_task(client: TestClient) -> None:
    client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    wait_for_status(client, 1, "waiting_for_user")
    response = client.post(f"{REQUIREMENT_ACTIONS}/open")
    assert response.status_code == 400
    assert "task #1 (implement) is still waiting_for_user on bulk-user-import" in response.text


@pytest.mark.usefixtures("requirement")
def test_open_pr_links_to_a_pull_request_the_branch_already_has(
    client: TestClient, fake_gh: FakeGh
) -> None:
    run_a_task(client)
    existing = "https://github.com/owner/sample/pull/41"
    fake_gh.add_pull_request(BRANCH, existing)
    response = client.post(f"{REQUIREMENT_ACTIONS}/open")
    assert response.status_code == 400
    assert "already has an open pull request" in response.text
    assert link(existing) in response.text
    assert OPEN_BUTTON not in response.text


@pytest.mark.usefixtures("requirement")
def test_pull_request_actions_are_posts_to_known_actions_on_known_requirements(
    client: TestClient,
) -> None:
    assert client.get(f"{REQUIREMENT_ACTIONS}/open").status_code == 405
    assert client.post(f"{REQUIREMENT_ACTIONS}/merge").status_code == 422
    assert (
        client.post("/repositories/1/requirements/nothing.md/pull-request/open").status_code == 404
    )
    assert client.post("/tasks/999/pull-request/open").status_code == 404


# ---------------------------------------------------------------- template sync page


@pytest.mark.usefixtures("requirement")
def test_a_completed_syncs_page_says_its_branch_is_local_and_offers_a_pull_request(
    client: TestClient,
) -> None:
    html = client.get(sync(client)).text
    assert f"<code>agent/template-sync-1</code> {ONLY_LOCAL}" in html
    assert 'action="http://testserver/tasks/1/pull-request/open" target="_blank"' in html
    assert OPEN_BUTTON in html


@pytest.mark.usefixtures("requirement")
def test_open_pr_from_a_syncs_page_opens_the_pull_request_on_github(
    client: TestClient, remote_repo: Path, fake_gh: FakeGh
) -> None:
    page = sync(client)
    response = client.post(f"{page}/pull-request/open", follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"] == PULL
    html = client.get(page).text
    assert link(PULL) in html
    assert "agent/template-sync-1" in remote_branches(remote_repo)
    created = fake_gh.calls[-1]
    assert created[created.index("--title") + 1] == "Sync with the repo template"
    assert created[created.index("--body") + 1] == "Files changed:\n\n- `CLAUDE.md`\n"
    assert 'action="http://testserver/tasks/1/pull-request/push"' in html
    assert 'action="http://testserver/tasks/1/pull-request/review"' in html
    merge = f'Merge <a href="{PULL}" target="_blank" rel="noopener noreferrer">its pull request</a>'
    assert f"{merge} on GitHub, then fetch." in client.get("/repositories/1").text


@pytest.mark.usefixtures("requirement")
def test_push_and_review_work_from_a_syncs_page(
    client: TestClient, settings: Settings, remote_repo: Path, fake_gh: FakeGh
) -> None:
    page = sync(client)
    client.post(f"{page}/pull-request/open")
    head = commit_in(worktree(settings, "template-sync-1"))
    pushed = client.post(f"{page}/pull-request/push")
    assert "Pushed <code>agent/template-sync-1</code>." in pushed.text
    assert run_git("rev-parse", "agent/template-sync-1", cwd=remote_repo) == head
    reviewed = client.post(f"{page}/pull-request/review")
    assert "Asked Copilot to review the pull request." in reviewed.text
    assert fake_gh.calls[-1] == ["pr", "edit", PULL, "--add-reviewer", "@copilot"]


@pytest.mark.usefixtures("requirement")
def test_a_refused_action_shows_its_reason_on_the_syncs_page(
    client: TestClient, fake_gh: FakeGh, remote_repo: Path
) -> None:
    page = sync(client)
    fake_gh.log_out()
    response = client.post(f"{page}/pull-request/open")
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert "isn&#39;t logged in to github.com" in response.text
    assert remote_branches(remote_repo) == ["main"]


@pytest.mark.usefixtures("requirement")
def test_a_requirements_task_page_offers_no_pull_request_of_its_own(client: TestClient) -> None:
    run_a_task(client)
    html = client.get("/tasks/1").text
    assert "Pull request" not in html
    response = client.post("/tasks/1/pull-request/open")
    assert response.status_code == 400
    assert "task #1 isn&#39;t a template sync" in response.text


@pytest.mark.usefixtures("requirement")
def test_a_sync_that_failed_offers_no_pull_request(client: TestClient, settings: Settings) -> None:
    (settings.worktrees_root / "sample").mkdir(parents=True)
    (settings.worktrees_root / "sample" / "template-sync-1").write_text("in the way\n")
    html = client.get(sync(client)).text
    assert 'class="status status-failed">failed<' in html
    assert "Pull request" not in html
    response = client.post("/tasks/1/pull-request/open")
    assert response.status_code == 400
    assert "template sync #1 is failed" in response.text


# ---------------------------------------------------------------- only on a click


@pytest.mark.usefixtures("requirement")
def test_no_task_status_change_or_page_load_pushes_or_asks_github(
    client: TestClient, remote_repo: Path, fake_gh: FakeGh
) -> None:
    client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    wait_for_status(client, 1, "waiting_for_user")
    client.post("/tasks/1/instructions", data={"text": "Carry on."})
    wait_for_status(client, 1, "waiting_for_user")
    client.post("/tasks/1/done")
    wait_for_status(client, 1, "completed")
    client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    wait_for_status(client, 2, "waiting_for_user")
    client.post("/tasks/2/cancel")
    wait_for_status(client, 2, "cancelled")
    page = sync(client)
    for address in (
        "/",
        "/repositories/1",
        "/repositories/1/requirements/bulk-user-import.md",
        "/tasks/1",
        "/tasks/2",
        page,
    ):
        assert client.get(address).status_code == 200
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


@pytest.mark.usefixtures("requirement")
@pytest.mark.parametrize("action", ["open", "push", "review"])
def test_an_action_sent_from_another_site_neither_pushes_nor_asks_github(
    client: TestClient, remote_repo: Path, fake_gh: FakeGh, action: str
) -> None:
    run_a_task(client)
    response = client.post(
        f"{REQUIREMENT_ACTIONS}/{action}", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


@pytest.mark.usefixtures("requirement")
def test_no_action_ever_passes_git_a_force_flag(
    client: TestClient, settings: Settings, git_calls: Callable[[], list[list[str]]]
) -> None:
    run_a_task(client)
    client.post(f"{REQUIREMENT_ACTIONS}/open")
    commit_in(worktree(settings))
    client.post(f"{REQUIREMENT_ACTIONS}/push")
    client.post(f"{REQUIREMENT_ACTIONS}/review")
    client.post(f"{sync(client)}/pull-request/open")
    pushes = [call for call in git_calls() if call[0] == "push"]
    assert len(pushes) == 3
    forcing = [arg for call in pushes for arg in call if arg == "-f" or arg.startswith("--force")]
    assert forcing == []
    assert not [call for call in pushes if any(arg.startswith("+") for arg in call)]


@pytest.mark.usefixtures("requirement")
def test_a_new_pull_request_opens_from_the_page_after_the_last_one_was_merged(
    client: TestClient, settings: Settings, fake_gh: FakeGh
) -> None:
    run_a_task(client)
    client.post(f"{REQUIREMENT_ACTIONS}/open")
    fake_gh.close_pull_requests()
    commit_in(worktree(settings))
    refused = client.post(f"{REQUIREMENT_ACTIONS}/push")
    assert refused.status_code == 400
    assert f"{PULL} is no longer open on GitHub" in refused.text
    assert f'action="{REQUIREMENT_ACTIONS}/open"' in refused.text
    reopened = client.post(f"{REQUIREMENT_ACTIONS}/open", follow_redirects=False)
    second = "https://github.com/owner/sample/pull/2"
    assert reopened.status_code == 303 and reopened.headers["location"] == second
    assert link(second) in client.get("/repositories/1/requirements/bulk-user-import.md").text
