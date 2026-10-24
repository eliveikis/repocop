"""Template sync pages: the plan with per-file picks, applying it, and the resulting task."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import run_git, write_template


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


@pytest.fixture
def registered(client: TestClient, remote_repo: Path) -> None:
    client.post("/repositories", data={"remote_url": str(remote_repo)})


def waiting_notice(html: str) -> str:
    """What a page says is left to do before a waiting sync lands."""
    match = re.search(r'<div class="notice sync-waiting">(.*?)</div>', html, re.DOTALL)
    assert match, "no waiting sync notice"
    return match[1]


def commit_the_template(settings: Settings) -> None:
    write_template(settings.template_dir, checkout(settings))
    run_git("add", "-A", cwd=checkout(settings))
    run_git("commit", "-qm", "Add the template", cwd=checkout(settings))
    run_git("push", "-q", "origin", "main", cwd=checkout(settings))


def test_sync_page_says_a_repository_with_no_commits_needs_one(
    client: TestClient, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.git"
    run_git("init", "-q", "--bare", str(empty), cwd=tmp_path)
    client.post("/repositories", data={"remote_url": str(empty)})
    html = client.get("/repositories/1/sync").text
    assert "empty has no commits yet. Make a first commit on" in html
    assert "<form" not in html


@pytest.mark.usefixtures("registered")
def test_repository_page_links_to_the_sync_page(client: TestClient) -> None:
    html = client.get("/repositories/1").text
    assert 'href="http://testserver/repositories/1/sync">Sync with template</a>' in html


@pytest.mark.usefixtures("registered")
def test_sync_page_picks_every_offered_file_by_default(
    client: TestClient, settings: Settings
) -> None:
    commit_the_template(settings)
    (checkout(settings) / "CLAUDE.md").write_text("# <b>Mine</b>\n")
    (checkout(settings) / "logo.bin").unlink()
    run_git("add", "-A", cwd=checkout(settings))
    run_git("commit", "-qm", "Customise", cwd=checkout(settings))
    run_git("push", "-q", "origin", "main", cwd=checkout(settings))
    html = client.get("/repositories/1/sync").text
    assert 'name="create" value="logo.bin" checked' in html
    assert 'name="overwrite" value="CLAUDE.md" checked' in html
    assert '<span class="diff-del">-# &lt;b&gt;Mine&lt;/b&gt;</span>' in html
    assert '<span class="diff-add">+# sample</span>' in html
    assert "<b>Mine</b>" not in html


@pytest.mark.usefixtures("registered")
def test_sync_page_picks_a_marked_file_the_template_retired_for_deletion(
    client: TestClient, settings: Settings
) -> None:
    commit_the_template(settings)
    rule = checkout(settings) / ".claude" / "rules" / "design.md"
    rule.parent.mkdir(parents=True)
    rule.write_text("<!-- managed by template -->\n# Design\n")
    (checkout(settings) / "notes.md").write_text("# Notes\n")
    run_git("add", "-A", cwd=checkout(settings))
    run_git("commit", "-qm", "Add a retired rule", cwd=checkout(settings))
    run_git("push", "-q", "origin", "main", cwd=checkout(settings))
    html = client.get("/repositories/1/sync").text
    assert "<td>removed from the template</td>" in html
    assert 'name="delete" value=".claude/rules/design.md" checked' in html
    assert '<span class="diff-del">-# Design</span>' in html
    assert "notes.md" not in html
    response = client.post(
        "/repositories/1/sync", data={"delete": [".claude/rules/design.md"]}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "- delete .claude/rules/design.md" in client.get(response.headers["location"]).text


@pytest.mark.usefixtures("registered")
def test_sync_page_says_when_the_repository_is_up_to_date(
    client: TestClient, settings: Settings
) -> None:
    commit_the_template(settings)
    html = client.get("/repositories/1/sync").text
    assert "Up to date" in html
    assert "<form" not in html


@pytest.mark.usefixtures("registered")
def test_applying_the_sync_opens_its_completed_task(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/repositories/1/sync", data={"create": ["CLAUDE.md"]}, follow_redirects=False
    )
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "<h1>#1 · template-sync</h1>" in html
    assert 'class="status status-completed">completed<' in html
    assert "<code>agent/template-sync-1</code>" in html
    worktree = settings.worktrees_root / "sample" / "template-sync-1"
    assert f'<code>{worktree}</code> <span class="owner owner-repocop">' in html
    assert '<span class="diff-add">+# sample</span>' in html
    assert "- create CLAUDE.md" in html


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_its_template_syncs(client: TestClient) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    html = client.get("/repositories/1").text
    assert '<a href="http://testserver/tasks/1">#1</a>' in html
    assert "agent/template-sync-1" in html


@pytest.mark.usefixtures("registered")
def test_applying_nothing_changes_nothing(client: TestClient, settings: Settings) -> None:
    response = client.post("/repositories/1/sync", data={})
    assert response.status_code == 200
    assert "Nothing was picked" in response.text
    assert not (settings.worktrees_root / "sample").exists()


@pytest.mark.usefixtures("registered")
def test_applying_a_file_the_plan_does_not_offer_says_why(client: TestClient) -> None:
    response = client.post("/repositories/1/sync", data={"create": ["README.md"]})
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert "reload the plan" in response.text


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_sync_pages_for_an_unknown_repository_are_not_found(
    client: TestClient, method: str
) -> None:
    assert client.request(method, "/repositories/999/sync").status_code == 404


@pytest.mark.usefixtures("registered", "declared_kinds")
def test_sync_page_offers_merges_and_leaves_starter_files_to_the_repository(
    client: TestClient, settings: Settings
) -> None:
    commit_the_template(settings)
    (checkout(settings) / "CLAUDE.md").write_text("# Mine\n")
    (checkout(settings) / ".claude" / "settings.json").write_text("{}\n")
    run_git("add", "-A", cwd=checkout(settings))
    run_git("commit", "-qm", "Customise", cwd=checkout(settings))
    run_git("push", "-q", "origin", "main", cwd=checkout(settings))
    html = client.get("/repositories/1/sync").text
    assert 'name="merge" value=".claude/settings.json" checked' in html
    assert 'value="CLAUDE.md"' not in html
    assert "the repository&#39;s own" in html
    response = client.post(
        "/repositories/1/sync", data={"merge": [".claude/settings.json"]}, follow_redirects=False
    )
    assert response.status_code == 303


@pytest.mark.usefixtures("registered", "declared_kinds")
def test_sync_page_says_why_a_merged_file_cannot_be_merged(
    client: TestClient, settings: Settings
) -> None:
    commit_the_template(settings)
    (checkout(settings) / ".claude" / "settings.json").write_text("{not json\n")
    run_git("add", "-A", cwd=checkout(settings))
    run_git("commit", "-qm", "Break", cwd=checkout(settings))
    run_git("push", "-q", "origin", "main", cwd=checkout(settings))
    html = client.get("/repositories/1/sync").text
    assert "can&#39;t merge: not valid JSON" in html
    assert 'name="merge"' not in html


@pytest.mark.usefixtures("registered")
def test_a_waiting_sync_shows_in_the_status_and_links_to_its_task(client: TestClient) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md", "logo.bin"]})
    for page in ("/", "/repositories/1"):
        html = client.get(page).text
        assert 'href="http://testserver/tasks/1">sync #1 not on main</a>' in html
        assert "behind the template" not in html


@pytest.mark.usefixtures("registered")
def test_a_waiting_sync_says_what_is_left_to_do_beside_a_fetch(client: TestClient) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    for page in ("/repositories/1", "/tasks/1", "/repositories/1/sync"):
        left = waiting_notice(client.get(page).text)
        assert "<code>agent/template-sync-1</code>, isn't on <code>origin/main</code>" in left
        assert "Open its pull request, merge it on GitHub, then fetch." in left
        assert 'action="http://testserver/repositories/1/fetch"' in left, page


@pytest.mark.usefixtures("registered")
def test_sync_page_points_at_a_waiting_sync_instead_of_offering_another(
    client: TestClient,
) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    html = client.get("/repositories/1/sync").text
    assert '<a href="http://testserver/tasks/1">' in html
    assert "agent/template-sync-1" in html
    assert 'action="http://testserver/repositories/1/sync"' not in html


@pytest.mark.usefixtures("registered")
def test_repository_page_shows_each_syncs_state_and_offers_to_remove_it(
    client: TestClient,
) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    html = client.get("/repositories/1").text
    assert "<td>waiting</td>" in html
    assert 'action="http://testserver/repositories/1/syncs/1/remove"' in html


@pytest.mark.usefixtures("registered")
def test_removing_a_sync_deletes_its_branch_and_offers_its_picks_again(
    client: TestClient, settings: Settings
) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    response = client.post("/repositories/1/syncs/1/remove", follow_redirects=False)
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "Removed <code>agent/template-sync-1</code> and its worktree." in html
    assert "<td>removed</td>" in html
    assert "syncs/1/remove" not in html
    assert run_git("branch", "--list", "agent/template-sync-1", cwd=checkout(settings)) == ""
    assert 'name="create" value="CLAUDE.md" checked' in client.get("/repositories/1/sync").text


@pytest.mark.usefixtures("registered")
def test_removing_a_sync_with_uncommitted_changes_says_why(
    client: TestClient, settings: Settings
) -> None:
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    worktree = settings.worktrees_root / "sample" / "template-sync-1"
    (worktree / "draft.txt").write_text("not committed\n")
    response = client.post("/repositories/1/syncs/1/remove")
    assert response.status_code == 400
    assert "uncommitted" in response.text
    assert worktree.is_dir()
