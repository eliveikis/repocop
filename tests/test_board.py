"""The fleet board on the main page: every requirement in every repository by its stage, read
from the repository and GitHub however the work was done, and Fetch all."""

import re
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import add_requirement, push_commit, run_git
from tests.fakes.fake_gh import FakeGh

PULL = "https://github.com/owner/sample/pull/7"


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


def stamp(days_ago: float) -> str:
    """An archive stamp from `days_ago` days ago, as `/complete-change` writes it."""
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H%M%SZ-")


def needs(*names: str) -> str:
    listed = "".join(f"  - {name}\n" for name in names)
    return f"---\ndepends-on:\n{listed}---\nSomething.\n"


def columns(html: str) -> dict[str, list[str]]:
    """The names of the cards in each of the board's stages."""
    found = re.findall(
        r'<section class="board-column" data-stage="([a-z-]+)".*?</section>', html, re.DOTALL
    )
    assert found, "no board"
    return {
        stage: re.findall(r'class="card-name"[^>]*>([^<]+)<', column)
        for stage, column in re.findall(
            r'<section class="board-column" data-stage="([a-z-]+)"(.*?)</section>',
            html,
            re.DOTALL,
        )
    }


def card(html: str, name: str) -> str:
    cards: list[str] = re.findall(r'<article class="card".*?</article>', html, re.DOTALL)
    found = [c for c in cards if re.search(rf'class="card-name"[^>]*>{re.escape(name)}<', c)]
    assert len(found) == 1, f"{name}: {len(found)} cards"
    return found[0]


def commit_on_branch(repo: Path, branch: str, file: str) -> None:
    """A commit on `branch`, made from the default branch, leaving `main` checked out."""
    run_git("switch", "-q", "-c", branch, "main", cwd=repo)
    (repo / file).write_text(f"{branch}\n")
    run_git("add", file, cwd=repo)
    run_git("commit", "-qm", f"Work on {branch}", cwd=repo)
    run_git("switch", "-q", "main", cwd=repo)


@pytest.fixture
def registered(client: TestClient, settings: Settings, remote_repo: Path) -> Path:
    """Repository `sample`, registered by its remote, and its checkout."""
    client.post("/repositories", data={"remote_url": str(remote_repo)})
    return checkout(settings)


@pytest.fixture
def pusher(remote_repo: Path, tmp_path: Path) -> Path:
    """Another clone of the remote, as a colleague's or an agent's elsewhere."""
    clone = tmp_path / "pusher"
    run_git("clone", "-q", str(remote_repo), str(clone), cwd=tmp_path)
    return clone


# ---------------------------------------------------------------- stages


def test_board_shows_each_requirement_by_its_stage(registered: Path, client: TestClient) -> None:
    add_requirement(registered, "todo-one.md")
    add_requirement(registered, "waits.md", needs("todo-one"))
    add_requirement(registered, "local-work.md")
    add_requirement(registered, f"{stamp(2)}shipped.md", folder="specs/changes/archive")
    commit_on_branch(registered, "local-work", "work.txt")
    commit_on_branch(registered, "xtodo-one", "other.txt")  # ends with its name, but isn't its
    html = client.get("/").text
    assert columns(html) == {
        "to-do": ["todo-one", "waits"],
        "in-progress": ["local-work"],
        "in-review": [],
        "delivered": ["shipped"],
    }
    assert ">todo-one</a>" in card(html, "waits")
    assert "2 days ago" in card(html, "shipped")
    page = "http://testserver/repositories/1/requirements/local-work.md"
    assert f'<a class="card-name" href="{page}">local-work</a>' in card(html, "local-work")
    assert "sample" in card(html, "local-work")


def test_board_names_each_branch_with_its_commits_and_whether_origin_has_them(
    registered: Path, pusher: Path, client: TestClient
) -> None:
    add_requirement(registered, "local-work.md")
    add_requirement(registered, "pushed-work.md")
    run_git("push", "-q", "origin", "main", cwd=registered)  # only the branches' own commits count
    commit_on_branch(registered, "agent/local-work", "a.txt")
    commit_on_branch(pusher, "eddie/pushed-work", "b.txt")
    (pusher / "c.txt").write_text("more\n")
    run_git("switch", "-q", "eddie/pushed-work", cwd=pusher)
    run_git("add", "c.txt", cwd=pusher)
    run_git("commit", "-qm", "More work", cwd=pusher)
    run_git("push", "-q", "origin", "eddie/pushed-work", cwd=pusher)
    client.post("/repositories/1/fetch")
    html = client.get("/").text
    assert columns(html)["in-progress"] == ["local-work", "pushed-work"]
    local = card(html, "local-work")
    assert "<code>agent/local-work</code>" in local
    assert "1 commit" in local and "not on origin yet" in local
    pushed = card(html, "pushed-work")
    assert "<code>eddie/pushed-work</code>" in pushed
    assert "2 commits" in pushed and "on origin" in pushed


def test_board_shows_a_change_delivered_on_origin_and_only_this_week(
    registered: Path, pusher: Path, client: TestClient
) -> None:
    add_requirement(registered, "landed.md")
    add_requirement(registered, f"{stamp(10)}old.md", folder="specs/changes/archive")
    add_requirement(registered, "unstamped.md", folder="specs/changes/archive")
    add_requirement(pusher, f"{stamp(0.1)}landed.md", folder="specs/changes/archive")
    run_git("push", "-q", "origin", "main", cwd=pusher)
    client.post("/repositories/1/fetch")
    assert columns(client.get("/").text) == {
        "to-do": [],
        "in-progress": [],
        "in-review": [],
        "delivered": ["landed"],
    }


def test_board_counts_a_change_archived_in_the_checkout_and_on_origin_once(
    registered: Path, client: TestClient
) -> None:
    add_requirement(registered, f"{stamp(1)}shipped.md", folder="specs/changes/archive")
    add_requirement(registered, "waits.md", needs("shipped"))
    run_git("push", "-q", "origin", "main", cwd=registered)  # archived on origin's main as well
    html = client.get("/").text
    assert columns(html)["delivered"] == ["shipped"]
    assert "Waits on" not in card(html, "waits")


def test_board_links_a_requirement_with_an_active_task_to_it(
    registered: Path, client: TestClient
) -> None:
    folder = registered / ".claude" / "skills" / "implement"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# implement\n")
    run_git("add", ".claude", cwd=registered)
    run_git("commit", "-qm", "Add skills", cwd=registered)
    add_requirement(registered, "bulk-user-import.md")
    response = client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 5
    while "status-waiting_for_user" not in client.get("/tasks/1/header").text:
        assert time.monotonic() < deadline, "the task never waited for the user"
        time.sleep(0.02)
    html = client.get("/").text
    assert columns(html)["in-progress"] == ["bulk-user-import"]
    assert 'href="http://testserver/tasks/1"' in card(html, "bulk-user-import")


def test_board_says_to_fetch_first_and_shows_no_branch_state_without_origins_default_branch(
    registered: Path, client: TestClient
) -> None:
    add_requirement(registered, "local-work.md")
    commit_on_branch(registered, "local-work", "a.txt")
    run_git("update-ref", "-d", "refs/remotes/origin/main", cwd=registered)
    html = client.get("/").text
    assert columns(html)["to-do"] == ["local-work"]
    assert "<code>local-work</code>" not in card(html, "local-work")
    notes = re.search(r'<ul class="board-notes">(.*?)</ul>', html, re.DOTALL)
    assert notes and "origin/main isn&#39;t in sample&#39;s checkout. Fetch first" in notes[1]


def test_board_reads_branches_with_a_fixed_number_of_git_calls(
    registered: Path, client: TestClient, git_calls: Callable[[], list[list[str]]]
) -> None:
    add_requirement(registered, "one.md")
    add_requirement(registered, "two.md")
    commit_on_branch(registered, "one", "a.txt")
    before = len(git_calls())
    client.get("/")
    with_one = len(git_calls()) - before
    for branch in ("two", "agent/one", "agent/two"):
        commit_on_branch(registered, branch, f"{branch.replace('/', '-')}.txt")
    before = len(git_calls())
    client.get("/")
    assert len(git_calls()) - before == with_one


# ---------------------------------------------------------------- pull requests


@pytest.fixture
def on_github(
    client: TestClient, github_checkout: Path, fake_gh: FakeGh, settings: Settings
) -> Path:
    """Repository `sample` on github.com, registered from its checkout, with `pushed-work`
    pushed and an open pull request for it."""
    client.post("/repositories", data={"name": "sample"})
    add_requirement(github_checkout, "pushed-work.md")
    add_requirement(github_checkout, "forked-work.md")
    commit_on_branch(github_checkout, "pushed-work", "a.txt")
    run_git("push", "-q", "origin", "pushed-work", cwd=github_checkout)
    client.post("/repositories/1/fetch")
    fake_gh.add_pull_request("pushed-work", PULL)
    fake_gh.add_pull_request("forked-work", "https://github.com/fork/sample/pull/8", fork=True)
    return github_checkout


@pytest.mark.usefixtures("on_github")
def test_main_page_shows_the_board_before_github_answers(
    client: TestClient, fake_gh: FakeGh
) -> None:
    calls = len(fake_gh.calls)
    html = client.get("/").text
    assert len(fake_gh.calls) == calls
    assert columns(html)["in-progress"] == ["pushed-work"]
    assert 'hx-get="http://testserver/board" hx-trigger="load"' in html
    assert 'href="http://testserver/?pull_requests=true"' in html  # without JavaScript


@pytest.mark.usefixtures("on_github")
def test_board_moves_a_requirement_with_an_open_pull_request_to_in_review(
    client: TestClient, fake_gh: FakeGh
) -> None:
    for page in ("/board", "/?pull_requests=true"):
        html = client.get(page).text
        assert columns(html)["in-review"] == ["pushed-work"], page
        assert columns(html)["to-do"] == ["forked-work"], page  # a fork's pull request isn't its
        assert f'<a href="{PULL}"' in card(html, "pushed-work")
        assert "hx-get" not in html.partition('id="board"')[2].partition(">")[0]
    asked = {tuple(call[:2]) for call in fake_gh.calls}
    assert asked <= {("auth", "status"), ("pr", "list")}  # reading changes nothing on GitHub


@pytest.mark.usefixtures("on_github")
def test_board_says_why_pull_requests_cant_be_read_and_keeps_its_stages(
    client: TestClient, fake_gh: FakeGh
) -> None:
    fake_gh.log_out()
    html = client.get("/board").text
    assert columns(html)["in-progress"] == ["pushed-work"]
    assert "sample: the GitHub CLI isn&#39;t logged in to github.com" in html


@pytest.mark.usefixtures("registered", "fake_gh")
def test_board_says_a_repository_not_on_github_has_no_pull_requests(client: TestClient) -> None:
    html = client.get("/board").text
    assert "isn&#39;t a repository on github.com, so it has no pull requests" in html


# ---------------------------------------------------------------- the fleet


@pytest.mark.usefixtures("registered")
def test_main_page_says_how_many_files_a_sync_would_offer(client: TestClient) -> None:
    sync_page = client.get("/repositories/1/sync").text
    offered = len(
        re.findall(r'type="checkbox" name="(?:create|overwrite|merge|delete)"', sync_page)
    )
    assert offered > 1
    link = f'<a href="http://testserver/repositories/1/sync">{offered} files to sync</a>'
    assert link in client.get("/").text


def test_fetch_all_fetches_every_repository_and_reports_each(
    registered: Path, client: TestClient, remote_repo: Path, tmp_path: Path
) -> None:
    other = tmp_path / "remotes" / "other.git"
    run_git("clone", "-q", "--bare", str(remote_repo), str(other), cwd=tmp_path)
    client.post("/repositories", data={"remote_url": str(other)})
    shutil.rmtree(other)
    push_commit(remote_repo, tmp_path)
    response = client.post("/repositories/fetch-all")
    assert response.status_code == 200
    html = response.text
    assert "Fetched 1 of 2 repositories." in html
    failed = re.search(r'<ul class="fetch-failures"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert failed and "<li>other: " in failed[1] and "sample" not in failed[1]
    assert "<div>0 ahead, 1 behind <code>origin/main</code></div>" in html
