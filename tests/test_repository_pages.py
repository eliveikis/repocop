"""Repository pages: the list with status, path ownership and checkout state, the Add repository
flow, fetch, and editor links."""

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from repocop.config import Settings
from repocop.main import create_app
from tests.conftest import push_commit, run_git, write_template
from tests.fakes.fake_claude import FakeClaudeFactory


@pytest.fixture
def linked(settings: Settings, fake_claude: FakeClaudeFactory) -> Iterator[TestClient]:
    """The app with an editor configured."""
    with_editor = settings.model_copy(update={"editor_url": "editor://open{path}/"})
    with TestClient(create_app(with_editor, claude_client=fake_claude)) as test_client:
        yield test_client


def add(client: TestClient, remote_url: str, name: str = "") -> str:
    """Post the Add repository form and return the page it redirects to."""
    response = client.post(
        "/repositories", data={"remote_url": remote_url, "name": name}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return client.get(response.headers["location"]).text


def row_names(html: str) -> list[str]:
    return re.findall(r'<td class="name"><a [^>]*>([^<]*)</a></td>', html)


def test_repository_list_shows_empty_state_and_add_form(client: TestClient) -> None:
    html = client.get("/").text
    assert "<h1>Repositories</h1>" in html
    assert "No repositories registered yet." in html
    assert 'action="http://testserver/repositories"' in html
    assert 'name="remote_url"' in html


def test_repository_list_labels_host_path_ownership(client: TestClient, settings: Settings) -> None:
    html = client.get("/").text
    assert "human-owned" in html
    assert "RepoCop-owned" in html
    assert str(settings.repos_root) in html
    assert str(settings.worktrees_root) in html


def test_add_repository_clones_and_lists_it(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    html = add(client, str(remote_repo))
    assert f"Cloned sample into {settings.repos_root / 'sample'}." in html
    assert row_names(html) == ["sample"]
    assert str(remote_repo) in html
    assert 'class="status status-behind"' in html


def test_add_repository_labels_the_repository_paths_by_owner(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    html = add(client, str(remote_repo))
    primary = f"<code>{settings.repos_root / 'sample'}</code> "
    worktrees = f"<code>{settings.worktrees_root / 'sample'}</code> "
    assert f'{primary}<span class="owner owner-human">human-owned</span>' in html
    assert f'{worktrees}<span class="owner owner-repocop">RepoCop-owned</span>' in html


def test_add_repository_registers_an_existing_checkout(
    client: TestClient, remote_repo: Path, primary_checkout: Path
) -> None:
    html = add(client, str(remote_repo))
    assert f"Registered the existing checkout at {primary_checkout}." in html


def test_add_repository_by_name_registers_an_existing_checkout(
    client: TestClient, remote_repo: Path, primary_checkout: Path
) -> None:
    assert 'name="remote_url" required' not in client.get("/").text
    html = add(client, "", name="sample")
    assert f"Registered the existing checkout at {primary_checkout}." in html
    assert f"<code>{remote_repo}</code>" in html


def test_a_remote_on_a_host_links_to_the_repositorys_page_there(
    client: TestClient, primary_checkout: Path
) -> None:
    run_git("remote", "set-url", "origin", "git@github.com:owner/repo.git", cwd=primary_checkout)
    add(client, "", name="sample")
    link = '<a href="https://github.com/owner/repo"><code>git@github.com:owner/repo.git</code></a>'
    assert link in client.get("/").text
    assert link in client.get("/repositories/1").text


def test_a_local_remote_is_not_a_link(client: TestClient, remote_repo: Path) -> None:
    add(client, str(remote_repo))
    assert f"<td><code>{remote_repo}</code></td>" in client.get("/").text
    assert f"<dd><code>{remote_repo}</code></dd>" in client.get("/repositories/1").text


def test_add_repository_by_the_name_of_a_missing_folder_says_why(client: TestClient) -> None:
    response = client.post("/repositories", data={"remote_url": "", "name": "sample"})
    assert response.status_code == 400
    assert "give its remote URL to clone it" in response.text
    assert 'value="sample"' in response.text


def test_add_repository_twice_does_not_duplicate_it(client: TestClient, remote_repo: Path) -> None:
    add(client, str(remote_repo))
    html = add(client, f"file://{remote_repo}")
    assert "sample is already registered." in html
    assert row_names(html) == ["sample"]


def test_add_repository_shows_errors_inline_and_keeps_the_input(client: TestClient) -> None:
    hostile = "https://github.com/<script>alert(1)</script>"
    response = client.post("/repositories", data={"remote_url": hostile, "name": ""})
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert "unsupported remote URL" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert 'value="https://github.com/&lt;script&gt;alert(1)&lt;/script&gt;"' in response.text


def test_repository_list_shows_a_missing_checkout(
    client: TestClient, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    add(client, str(remote_repo))
    (settings.repos_root / "sample").rename(tmp_path / "moved-away")
    assert 'class="status status-missing">missing<' in client.get("/").text


def test_registered_repositories_survive_a_restart(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    with TestClient(create_app(settings)) as restarted:
        assert row_names(restarted.get("/").text) == ["sample"]


def test_repository_list_links_a_repository_behind_the_template_to_its_sync_page(
    client: TestClient, remote_repo: Path
) -> None:
    html = add(client, str(remote_repo))
    assert 'href="http://testserver/repositories/1/sync">behind the template</a>' in html


def test_repository_page_links_a_repository_behind_the_template_to_its_sync_page(
    client: TestClient, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    html = client.get("/repositories/1").text
    assert 'href="http://testserver/repositories/1/sync">behind the template</a>' in html


def test_repository_up_to_date_with_the_template_is_ready(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    checkout = settings.repos_root / "sample"
    write_template(settings.template_dir, checkout)
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-qm", "Add the template", cwd=checkout)
    run_git("push", "-q", "origin", "main", cwd=checkout)
    assert 'class="status status-ready"' in client.get("/").text


def test_repository_with_no_commits_says_it_needs_one(client: TestClient, tmp_path: Path) -> None:
    empty = tmp_path / "empty.git"
    run_git("init", "-q", "--bare", str(empty), cwd=tmp_path)
    html = add(client, str(empty))
    assert '<span class="status status-no_commits">needs a first commit</span>' in html


def test_adding_a_repository_writes_nothing_into_its_checkout(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    checkout = settings.repos_root / "sample"
    assert run_git("status", "--porcelain", "--ignored", cwd=checkout) == ""
    assert not (checkout / "CLAUDE.md").exists()


def test_there_is_no_set_up_page(client: TestClient, remote_repo: Path) -> None:
    add(client, str(remote_repo))
    assert client.get("/repositories/1/setup").status_code == 404
    assert client.post("/repositories/1/setup").status_code in (404, 405)


def test_repository_list_ignores_an_unknown_registered_id(client: TestClient) -> None:
    response = client.get("/", params={"registered": 999, "outcome": "cloned"})
    assert response.status_code == 200
    assert "Cloned" not in response.text


def test_main_page_shows_claude_is_using_the_subscription(client: TestClient) -> None:
    html = client.get("/").text
    assert "Claude: your Claude subscription (Max, you@example.invalid)" in html


def test_main_page_shows_claude_is_using_an_api_key(
    settings: Settings, fake_claude: FakeClaudeFactory
) -> None:
    keyed = settings.model_copy(update={"anthropic_api_key": SecretStr("sk-ant-configured")})
    with TestClient(create_app(keyed, claude_client=fake_claude)) as client:
        html = client.get("/").text
    assert "Claude: an API key from RepoCop's configuration" in html
    assert "sk-ant-configured" not in html


def test_main_page_warns_when_claude_is_not_logged_in(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    html = client.get("/").text
    assert 'class="claude-auth claude-auth-problem"' in html
    assert "claude auth login" in html


# ---------------------------------------------------------------- checkout state


def test_repository_list_shows_each_checkouts_branch_changes_and_upstream(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    (settings.repos_root / "sample" / "notes.md").write_text("notes\n")
    html = client.get("/").text
    assert "<div><code>main</code></div>" in html
    assert "<div>1 changed file</div>" in html
    assert "<div>0 ahead, 0 behind <code>origin/main</code></div>" in html
    assert "as of each checkout's last fetch" in html


def test_repository_list_shows_a_detached_head(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    checkout = settings.repos_root / "sample"
    run_git("checkout", "-q", "--detach", cwd=checkout)
    commit = run_git("rev-parse", "HEAD", cwd=checkout)
    html = client.get("/").text
    assert f"detached at <code>{commit[:12]}</code>" in html
    assert "<div>no upstream</div>" in html


def test_repository_list_shows_an_unfinished_merge(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    checkout = settings.repos_root / "sample"
    run_git("checkout", "-q", "-b", "other", cwd=checkout)
    (checkout / "other.txt").write_text("other\n")
    run_git("add", "other.txt", cwd=checkout)
    run_git("commit", "-qm", "other", cwd=checkout)
    run_git("checkout", "-q", "main", cwd=checkout)
    run_git("merge", "-q", "--no-commit", "--no-ff", "other", cwd=checkout)
    assert '<span class="badge">merge unfinished</span>' in client.get("/").text


def test_a_missing_checkout_shows_no_checkout_state(
    client: TestClient, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    add(client, str(remote_repo))
    (settings.repos_root / "sample").rename(tmp_path / "moved-away")
    assert '<td class="checkout">—</td>' in client.get("/").text
    html = client.get("/repositories/1").text
    assert "Primary checkout" not in html
    assert "Fetch</button>" not in html


def test_a_git_failure_in_one_checkout_is_shown_there_and_the_pages_still_render(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    other = remote_repo.parent / "other.git"
    shutil.copytree(remote_repo, other)
    add(client, str(remote_repo))
    add(client, str(other))
    (settings.repos_root / "other" / ".git" / "index").write_bytes(b"not an index")
    listed = client.get("/")
    assert listed.status_code == 200
    assert "git status failed" in listed.text
    assert "<div>0 ahead, 0 behind <code>origin/main</code></div>" in listed.text
    page = client.get("/repositories/2")
    assert page.status_code == 200
    assert "<h1>other</h1>" in page.text
    assert "git status failed" in page.text


def test_repository_page_shows_the_checkout_state_and_lists_the_changed_files(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    checkout = settings.repos_root / "sample"
    (checkout / "README.md").write_text("edited\n")
    (checkout / "<b>notes.md").write_text("notes\n")
    html = client.get("/repositories/1").text
    assert "<div><code>main</code></div>" in html
    assert "<div>2 changed files</div>" in html
    assert "<li><code>README.md</code></li>" in html
    assert "<li><code>&lt;b&gt;notes.md</code></li>" in html
    assert "<div>0 ahead, 0 behind <code>origin/main</code></div>" in html
    assert "as of the last fetch" in html


def test_repository_page_names_an_upstream_that_fetch_does_not_refresh(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    add(client, str(remote_repo))
    checkout = settings.repos_root / "sample"
    run_git("remote", "add", "fork", str(remote_repo), cwd=checkout)
    run_git("fetch", "-q", "fork", cwd=checkout)
    run_git("branch", "-q", "--set-upstream-to=fork/main", cwd=checkout)
    html = client.get("/repositories/1").text
    assert "<div>0 ahead, 0 behind <code>fork/main</code></div>" in html
    assert "with its upstream, <code>fork/main</code>, as of the last fetch" in html
    assert "Fetch updates only <code>origin</code>'s remote-tracking branches" in html


# ---------------------------------------------------------------- fetch


def test_fetch_from_the_repository_page_shows_the_new_behind_count(
    client: TestClient, remote_repo: Path, tmp_path: Path
) -> None:
    add(client, str(remote_repo))
    push_commit(remote_repo, tmp_path)
    assert "0 ahead, 0 behind" in client.get("/repositories/1").text
    response = client.post("/repositories/1/fetch", follow_redirects=False)
    assert response.status_code == 303, response.text
    html = client.get(response.headers["location"]).text
    assert "Fetched from origin." in html
    assert "<div>0 ahead, 1 behind <code>origin/main</code></div>" in html


def test_fetch_failure_is_shown_inline(
    client: TestClient, remote_repo: Path, tmp_path: Path
) -> None:
    add(client, f"file://{remote_repo}")
    remote_repo.rename(tmp_path / "moved-away.git")
    response = client.post("/repositories/1/fetch")
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert "git fetch failed" in response.text


def test_fetch_of_a_missing_checkout_says_why(
    client: TestClient, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    add(client, str(remote_repo))
    (settings.repos_root / "sample").rename(tmp_path / "moved-away")
    response = client.post("/repositories/1/fetch")
    assert response.status_code == 400
    assert "isn&#39;t there" in response.text


def test_fetch_only_runs_on_a_post(client: TestClient, remote_repo: Path) -> None:
    add(client, str(remote_repo))
    assert client.get("/repositories/1/fetch").status_code == 405
    assert client.post("/repositories/999/fetch").status_code == 404


# ---------------------------------------------------------------- editor links


def test_repository_pages_link_the_checkout_to_the_editor(
    linked: TestClient, settings: Settings, remote_repo: Path
) -> None:
    listed = add(linked, str(remote_repo))
    link = f'<a href="editor://open{settings.repos_root / "sample"}/">Open in editor</a>'
    assert f'<span class="owner owner-human">human-owned</span> {link}' in listed
    assert link in linked.get("/repositories/1").text
    assert listed.count("Open in editor") == 1


def test_repository_pages_have_no_editor_link_without_the_setting(
    client: TestClient, remote_repo: Path
) -> None:
    assert "Open in editor" not in add(client, str(remote_repo))
    assert "Open in editor" not in client.get("/repositories/1").text


def test_a_missing_checkout_has_no_editor_link(
    linked: TestClient, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    add(linked, str(remote_repo))
    (settings.repos_root / "sample").rename(tmp_path / "moved-away")
    assert "Open in editor" not in linked.get("/").text
    assert "Open in editor" not in linked.get("/repositories/1").text
