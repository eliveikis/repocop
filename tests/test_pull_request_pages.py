"""Pull request actions on a completed template sync's page."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import run_git
from tests.fakes.fake_gh import FakeGh

BRANCH = "agent/template-sync-1"
PULL = "https://github.com/owner/sample/pull/1"
ACTIONS = "http://testserver/tasks/1/pull-request"


def link(url: str) -> str:
    """How a page links a pull request: in a new tab."""
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>'


OPEN_BUTTON = '<button type="submit">Open PR</button>'
OPEN_ANOTHER = '<button type="submit">Open a new PR</button>'
ONLY_LOCAL = "is only on this machine until its pull request is opened"


@pytest.fixture
def registered(client: TestClient, github_checkout: Path, fake_gh: FakeGh) -> None:
    """Repository `sample`, on github.com."""
    client.post(
        "/repositories", data={"remote_url": "", "name": "sample", "default_branch": "main"}
    )


def sync(client: TestClient) -> str:
    """Apply a template sync and return its page's address."""
    response = client.post(
        "/repositories/1/sync", data={"create": ["CLAUDE.md"]}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return str(response.headers["location"])


def worktree(settings: Settings) -> Path:
    return settings.worktrees_root / "sample" / "template-sync-1"


def commit_in(folder: Path) -> str:
    (folder / "work.txt").write_text("work\n")
    run_git("add", "work.txt", cwd=folder)
    run_git("commit", "-qm", "Work", cwd=folder)
    return run_git("rev-parse", "HEAD", cwd=folder)


def remote_branches(remote: Path) -> list[str]:
    return run_git("for-each-ref", "--format=%(refname:short)", cwd=remote).splitlines()


@pytest.mark.usefixtures("registered")
def test_a_completed_syncs_page_says_its_branch_is_local_and_offers_a_pull_request(
    client: TestClient,
) -> None:
    html = client.get(sync(client)).text
    assert f"<code>agent/template-sync-1</code> {ONLY_LOCAL}" in html
    assert 'action="http://testserver/tasks/1/pull-request/open" target="_blank"' in html
    assert OPEN_BUTTON in html


@pytest.mark.usefixtures("registered")
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


@pytest.mark.usefixtures("registered")
def test_push_and_review_work_from_a_syncs_page(
    client: TestClient, settings: Settings, remote_repo: Path, fake_gh: FakeGh
) -> None:
    page = sync(client)
    client.post(f"{page}/pull-request/open")
    head = commit_in(worktree(settings))
    pushed = client.post(f"{page}/pull-request/push")
    assert "Pushed <code>agent/template-sync-1</code>." in pushed.text
    assert run_git("rev-parse", "agent/template-sync-1", cwd=remote_repo) == head
    reviewed = client.post(f"{page}/pull-request/review")
    assert "Asked Copilot to review the pull request." in reviewed.text
    assert fake_gh.calls[-1] == ["pr", "edit", PULL, "--add-reviewer", "@copilot"]


@pytest.mark.usefixtures("registered")
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


@pytest.mark.usefixtures("registered")
def test_a_sync_that_failed_offers_no_pull_request(client: TestClient, settings: Settings) -> None:
    (settings.worktrees_root / "sample").mkdir(parents=True)
    (settings.worktrees_root / "sample" / "template-sync-1").write_text("in the way\n")
    html = client.get(sync(client)).text
    assert 'class="status status-failed">failed<' in html
    assert "Pull request" not in html
    response = client.post("/tasks/1/pull-request/open")
    assert response.status_code == 400
    assert "template sync #1 is failed" in response.text


@pytest.mark.usefixtures("registered")
def test_open_pr_links_to_a_pull_request_the_branch_already_has(
    client: TestClient, fake_gh: FakeGh
) -> None:
    sync(client)
    existing = "https://github.com/owner/sample/pull/41"
    fake_gh.add_pull_request(BRANCH, existing)
    response = client.post(f"{ACTIONS}/open")
    assert response.status_code == 400
    assert "already has an open pull request" in response.text
    assert link(existing) in response.text
    assert OPEN_BUTTON not in response.text


@pytest.mark.usefixtures("registered")
def test_a_new_pull_request_opens_from_the_page_after_the_last_one_was_merged(
    client: TestClient, settings: Settings, fake_gh: FakeGh
) -> None:
    page = sync(client)
    client.post(f"{ACTIONS}/open")
    fake_gh.close_pull_requests()
    commit_in(worktree(settings))
    refused = client.post(f"{ACTIONS}/push")
    assert refused.status_code == 400
    assert f"{PULL} is no longer open on GitHub" in refused.text
    assert f'action="{ACTIONS}/open"' in refused.text
    reopened = client.post(f"{ACTIONS}/open", follow_redirects=False)
    second = "https://github.com/owner/sample/pull/2"
    assert reopened.status_code == 303 and reopened.headers["location"] == second
    assert link(second) in client.get(page).text
    assert OPEN_ANOTHER in client.get(page).text


@pytest.mark.usefixtures("registered")
def test_pull_request_actions_are_posts_to_known_actions_on_known_syncs(
    client: TestClient,
) -> None:
    sync(client)
    assert client.get(f"{ACTIONS}/open").status_code == 405
    assert client.post(f"{ACTIONS}/merge").status_code == 422
    assert client.post("/tasks/999/pull-request/open").status_code == 404


# ---------------------------------------------------------------- only on a click


@pytest.mark.usefixtures("registered")
def test_no_sync_or_page_load_pushes_or_asks_github(
    client: TestClient, remote_repo: Path, fake_gh: FakeGh
) -> None:
    page = sync(client)
    for address in ("/", "/repositories/1", "/repositories/1/sync", page):
        assert client.get(address).status_code == 200
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


@pytest.mark.usefixtures("registered")
@pytest.mark.parametrize("action", ["open", "push", "review"])
def test_an_action_sent_from_another_site_neither_pushes_nor_asks_github(
    client: TestClient, remote_repo: Path, fake_gh: FakeGh, action: str
) -> None:
    sync(client)
    response = client.post(f"{ACTIONS}/{action}", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


@pytest.mark.usefixtures("registered")
def test_no_action_ever_passes_git_a_force_flag(
    client: TestClient, settings: Settings, git_calls: Callable[[], list[list[str]]]
) -> None:
    sync(client)
    client.post(f"{ACTIONS}/open")
    commit_in(worktree(settings))
    client.post(f"{ACTIONS}/push")
    client.post(f"{ACTIONS}/review")
    pushes = [call for call in git_calls() if call[0] == "push"]
    assert len(pushes) == 2
    forcing = [arg for call in pushes for arg in call if arg == "-f" or arg.startswith("--force")]
    assert forcing == []
    assert not [call for call in pushes if any(arg.startswith("+") for arg in call)]
