"""Task pages: start a workflow from a requirement, view the task, cancel it."""

import re
import sqlite3
import time
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repocop import db
from repocop.config import Settings
from repocop.main import create_app
from repocop.services import git, tasks
from repocop.services.tasks import Status
from tests.conftest import add_requirement, push_commit, run_git
from tests.fakes.fake_claude import FakeClaudeFactory


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


@pytest.fixture
def requirement(client: TestClient, settings: Settings, remote_repo: Path) -> None:
    """Repository `sample` with committed skills, and bulk-user-import committed in its checkout."""
    client.post("/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"})
    for name in ("implement", "review-requirement"):
        folder = checkout(settings) / ".claude" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=checkout(settings))
    run_git("commit", "-qm", "Add skills", cwd=checkout(settings))
    add_requirement(checkout(settings))


def wait_for_status(client: TestClient, task_id: int, status: str, timeout: float = 5.0) -> str:
    """The task page, once the background session has moved the task to `status`."""
    deadline = time.monotonic() + timeout
    while True:
        html = client.get(f"/tasks/{task_id}").text
        if f'class="status status-{status}">{status}<' in html.partition("<main")[2]:
            return html
        if time.monotonic() > deadline:
            raise AssertionError(f"task #{task_id} never reached {status}")
        time.sleep(0.02)


def start(client: TestClient, workflow: str = "implement") -> str:
    response = client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks",
        data={"workflow": workflow},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return client.get(response.headers["location"]).text


@pytest.mark.usefixtures("requirement")
def test_a_workflow_starts_on_a_hand_made_file_from_its_page(
    client: TestClient, settings: Settings
) -> None:
    folder = checkout(settings) / "specs/changes/todo"
    (folder / "search-notes.md").write_text("Faster search.\n")
    run_git("add", ".", cwd=checkout(settings))
    run_git("commit", "-qm", "Add search-notes", cwd=checkout(settings))
    page = "/repositories/1/requirements/search-notes.md"
    assert "<option>implement</option>" in client.get(page).text
    response = client.post(f"{page}/tasks", data={"workflow": "implement"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    html = client.get(response.headers["location"]).text
    assert "<code>agent/search-notes</code>" in html
    assert f'<a href="http://testserver{page}">search-notes</a>' in html


@pytest.mark.usefixtures("requirement")
def test_requirement_page_offers_the_committed_skills_as_workflows(client: TestClient) -> None:
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert "<option>implement</option>" in html
    assert "<option>review-requirement</option>" in html
    assert (
        'action="http://testserver/repositories/1/requirements/bulk-user-import.md/tasks"' in html
    )


def test_requirement_page_explains_when_no_skills_are_committed(
    client: TestClient, settings: Settings, remote_repo: Path
) -> None:
    client.post("/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"})
    add_requirement(checkout(settings), "x.md", "")
    html = client.get("/repositories/1/requirements/x.md").text
    assert "No skills are committed" in html
    assert 'href="http://testserver/repositories/1/sync">Sync with the template</a>' in html
    assert 'action="http://testserver/repositories/1/requirements/x.md/tasks"' not in html


@pytest.mark.usefixtures("requirement")
def test_start_task_opens_its_page_with_branch_and_worktree(
    client: TestClient, settings: Settings
) -> None:
    html = start(client)
    assert "<h1>#1 · implement</h1>" in html
    assert "Task started in its worktree." in html
    assert "<code>agent/bulk-user-import</code>" in html
    worktree = settings.worktrees_root / "sample" / "bulk-user-import"
    assert f'<code>{worktree}</code> <span class="owner owner-repocop">RepoCop-owned</span>' in html
    assert (
        '<a href="http://testserver/repositories/1/requirements/bulk-user-import.md">bulk-user-import</a>'
        in html
    )


@pytest.mark.usefixtures("requirement")
def test_task_page_shows_the_transcript_once_the_turn_ends(client: TestClient) -> None:
    start(client)
    html = wait_for_status(client, 1, "waiting_for_user")
    path = "specs/changes/todo/bulk-user-import.md"
    assert f"<pre>Following /implement for {path}.</pre>" in html
    assert "Tool · Read" in html
    assert "<pre>Done with /implement.</pre>" in html
    assert 'action="http://testserver/tasks/1/instructions"' in html
    assert 'action="http://testserver/tasks/1/done"' in html


@pytest.mark.usefixtures("requirement")
def test_requirement_page_lists_its_tasks(client: TestClient) -> None:
    start(client)
    html = client.get("/repositories/1/requirements/bulk-user-import.md").text
    assert '<a href="http://testserver/tasks/1">#1</a>' in html
    assert "<td>implement</td>" in html


@pytest.mark.usefixtures("requirement")
def test_start_task_with_uncommitted_changes_says_to_commit_first(
    client: TestClient, settings: Settings
) -> None:
    requirement_file = checkout(settings) / "specs/changes/todo/bulk-user-import.md"
    requirement_file.write_text("# Bulk user import\n\nEdited by hand.\n")
    response = client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    assert response.status_code == 400
    commit_first = "uncommitted changes. Commit specs/changes/todo/bulk-user-import.md first"
    assert commit_first in response.text
    assert "/commit" not in response.text


@pytest.mark.usefixtures("requirement")
def test_second_start_names_the_active_task(client: TestClient) -> None:
    start(client, "review-requirement")
    response = client.post(
        "/repositories/1/requirements/bulk-user-import.md/tasks", data={"workflow": "implement"}
    )
    assert response.status_code == 400
    assert re.search(
        r"task #1 \(review-requirement\) is still (running|waiting_for_user)", response.text
    )


@pytest.mark.usefixtures("requirement")
def test_cancel_task_ends_it(client: TestClient) -> None:
    start(client)
    response = client.post("/tasks/1/cancel", follow_redirects=False)
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "Task cancelled." in html
    assert 'class="status status-cancelled">cancelled<' in html
    assert 'action="http://testserver/tasks/1/cancel"' not in html


@pytest.mark.usefixtures("requirement")
def test_cancel_of_a_cancelled_task_says_why(client: TestClient) -> None:
    start(client)
    client.post("/tasks/1/cancel")
    response = client.post("/tasks/1/cancel")
    assert response.status_code == 400
    assert "can&#39;t be cancelled here" in response.text


@pytest.mark.usefixtures("requirement")
def test_instruction_from_the_task_page_reaches_its_session(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    response = client.post(
        "/tasks/1/instructions", data={"text": "Also add tests."}, follow_redirects=False
    )
    assert response.status_code == 303
    html = wait_for_status(client, 1, "waiting_for_user")
    assert '<span class="who">You</span><pre>Also add tests.</pre>' in html
    assert "<pre>Noted: Also add tests.</pre>" in html


@pytest.mark.usefixtures("requirement")
def test_empty_instruction_says_why(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    response = client.post("/tasks/1/instructions", data={"text": " "})
    assert response.status_code == 400
    assert "the instruction is empty" in response.text


@pytest.mark.usefixtures("requirement")
def test_mark_done_completes_a_waiting_task(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    response = client.post("/tasks/1/done", follow_redirects=False)
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "Task marked done." in html
    assert 'class="status status-completed">completed<' in html
    assert 'action="http://testserver/tasks/1/instructions"' not in html


@pytest.mark.usefixtures("requirement")
def test_a_restart_keeps_the_task_list_and_settles_running_tasks(
    client: TestClient, settings: Settings, fake_claude: FakeClaudeFactory
) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    with sqlite3.connect(settings.database_path) as raw:  # as if it was still running at a crash
        raw.execute("UPDATE tasks SET status = 'running' WHERE id = 1")
    with TestClient(create_app(settings, claude_client=fake_claude)) as restarted:
        assert (
            '<a href="http://testserver/tasks/1">#1</a>'
            in restarted.get("/repositories/1/requirements/bulk-user-import.md").text
        )
        html = restarted.get("/tasks/1").text
    assert 'class="status status-waiting_for_user">waiting_for_user<' in html
    conn = db.connect(settings.database_path)
    try:
        kinds = [row[0] for row in conn.execute("SELECT kind FROM task_events WHERE task_id = 1")]
    finally:
        conn.close()
    assert kinds[-1] == "status_change"


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/tasks/999"),
        ("POST", "/tasks/999/cancel"),
        ("POST", "/tasks/999/instructions"),
        ("POST", "/tasks/999/done"),
        ("POST", "/tasks/999/again"),
        ("GET", "/tasks/999/header"),
        ("GET", "/tasks/999/events"),
        ("GET", "/tasks/999/worktree"),
        ("POST", "/requirements/999/tasks"),
    ],
)
def test_task_pages_for_unknown_ids_are_not_found(
    client: TestClient, method: str, url: str
) -> None:
    assert client.request(method, url, data={"workflow": "implement"}).status_code == 404


@pytest.mark.usefixtures("requirement")
def test_task_page_shows_why_a_task_failed(client: TestClient, settings: Settings) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    conn = db.connect(settings.database_path)
    try:
        tasks.transition(conn, 1, Status.RUNNING)
        tasks.transition(conn, 1, Status.FAILED, error="Claude Code exited with code 1")
    finally:
        conn.close()
    html = client.get("/tasks/1").text
    assert 'class="status status-failed">failed<' in html
    assert '<dd class="error-text">Claude Code exited with code 1</dd>' in html


@pytest.mark.usefixtures("requirement")
def test_task_page_explains_an_interruption_by_a_restart(
    client: TestClient, settings: Settings, fake_claude: FakeClaudeFactory
) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    worktree = settings.worktrees_root / "sample" / "bulk-user-import"
    (worktree / "half.txt").write_text("half done\n")
    with sqlite3.connect(settings.database_path) as raw:  # as if it was still running at a crash
        raw.execute("UPDATE tasks SET status = 'running' WHERE id = 1")
    with TestClient(create_app(settings, claude_client=fake_claude)) as restarted:
        html = restarted.get("/tasks/1").text
    assert "RepoCop restarted during this task." in html
    assert "0 commits since it started" in html
    assert "<li><code>half.txt</code></li>" in html
    assert "Send an instruction below to resume its session" in html


@pytest.mark.usefixtures("requirement")
def test_start_again_runs_the_same_workflow_in_the_same_worktree(
    client: TestClient, settings: Settings
) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    client.post("/tasks/1/cancel")
    response = client.post("/tasks/1/again", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/tasks/2?started=true")
    html = wait_for_status(client, 2, "waiting_for_user")
    assert "<h1>#2 · implement</h1>" in html
    worktree = settings.worktrees_root / "sample" / "bulk-user-import"
    assert f"<code>{worktree}</code>" in html


@pytest.mark.usefixtures("requirement")
def test_start_again_of_a_task_still_active_says_why(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    assert 'action="http://testserver/tasks/1/again"' not in client.get("/tasks/1").text
    response = client.post("/tasks/1/again")
    assert response.status_code == 400
    assert "only a failed or cancelled task can start again" in response.text


# ---------------------------------------------------------------- worktree and live updates


def worktree(settings: Settings) -> Path:
    return settings.worktrees_root / "sample" / "bulk-user-import"


@pytest.mark.usefixtures("requirement")
def test_task_page_loads_only_the_vendored_htmx_and_the_shell_script(client: TestClient) -> None:
    start(client)
    html = client.get("/tasks/1").text
    scripts = re.findall(r'<script src="http://testserver(/static/[^"]+)" defer></script>', html)
    assert scripts == ["/static/vendor/htmx.min.js", "/static/js/shell.js"]
    assert html.count("<script") == len(scripts)
    for path in scripts:
        script = client.get(path)
        assert script.status_code == 200
        assert "javascript" in script.headers["content-type"]


@pytest.mark.usefixtures("requirement")
def test_task_page_shows_git_status_and_the_diff(client: TestClient, settings: Settings) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    (worktree(settings) / "notes.txt").write_text("a new note\n")
    html = client.get("/tasks/1").text
    assert "?? notes.txt" in html
    assert '<span class="diff-add">+a new note</span>' in html


@pytest.mark.usefixtures("requirement")
def test_task_page_says_when_part_of_the_diff_is_left_out(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    monkeypatch.setattr(git, "MAX_NEW_FILES_IN_DIFF", 1)
    for name in ("a.txt", "b.txt"):
        (worktree(settings) / name).write_text(f"{name}\n")
    html = client.get("/tasks/1/worktree").text
    assert "… and 1 more new file not shown" in html
    assert "Only part of the diff is shown" in html


@pytest.mark.usefixtures("requirement")
def test_task_page_escapes_the_diff(client: TestClient, settings: Settings) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    (worktree(settings) / "page.html").write_text("<script>alert(1)</script>\n")
    html = client.get("/tasks/1").text
    assert "<script>alert(1)</script>" not in html
    assert "+&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.usefixtures("requirement")
def test_task_page_polls_while_the_task_is_active_and_stops_after(client: TestClient) -> None:
    start(client)
    active = wait_for_status(client, 1, "waiting_for_user")
    assert active.partition("<main")[2].count('hx-trigger="every 2s"') == 3
    client.post("/tasks/1/cancel")
    assert 'hx-trigger="every 2s"' not in client.get("/tasks/1").text


@pytest.mark.usefixtures("requirement")
def test_events_fragment_returns_only_newer_events(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    everything = client.get("/tasks/1/events", params={"after": 0}).text
    assert "<pre>Done with /implement.</pre>" in everything
    last = int(re.findall(r"after=(\d+)", everything)[-1])
    newer = client.get("/tasks/1/events", params={"after": last}).text
    assert "<pre>" not in newer
    assert f"after={last}" in newer


@pytest.mark.usefixtures("requirement")
def test_events_fragment_stops_polling_once_the_task_has_ended(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    client.post("/tasks/1/cancel")
    fragment = client.get("/tasks/1/events", params={"after": 999}).text
    assert "hx-trigger" not in fragment


@pytest.mark.usefixtures("requirement")
def test_header_fragment_shows_the_current_status(client: TestClient) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    header = client.get("/tasks/1/header").text
    assert 'class="status status-waiting_for_user">waiting_for_user<' in header
    assert 'hx-trigger="every 2s"' in header


@pytest.mark.usefixtures("requirement")
def test_worktree_fragment_says_when_the_worktree_is_gone(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    worktree(settings).rename(tmp_path / "moved-away")
    assert "isn't there any more" in client.get("/tasks/1/worktree").text


def session_id(html: str) -> str:
    match = re.search(r"<dt>Session</dt><dd><code>([^<]+)</code>", html)
    assert match is not None
    return match.group(1)


@pytest.mark.usefixtures("requirement")
def test_task_page_offers_to_continue_the_session_in_a_terminal_once_it_has_ended(
    client: TestClient, settings: Settings
) -> None:
    start(client)
    waiting = wait_for_status(client, 1, "waiting_for_user")
    assert "--resume" not in waiting
    assert "mark it done or cancel it first" in waiting
    client.post("/tasks/1/done")
    html = client.get("/tasks/1").text
    resume = f"{settings.claude_bin} --resume {session_id(html)}"
    command = f"cd {worktree(settings)} &amp;&amp; {resume}"
    assert f"<pre><code>{command}</code></pre>" in html


def configure_editor(client: TestClient, settings: Settings) -> None:
    """Give the running app an editor, as if `editor_url` had been configured."""
    app = cast("FastAPI", client.app)
    app.state.settings = settings.model_copy(update={"editor_url": "editor://open{path}/"})


@pytest.mark.usefixtures("requirement")
def test_task_page_links_its_worktree_to_the_editor(client: TestClient, settings: Settings) -> None:
    configure_editor(client, settings)
    start(client)
    link = f'<a href="editor://open{worktree(settings)}/">Open in editor</a>'
    owner = '<span class="owner owner-repocop">RepoCop-owned</span>'
    assert f"{owner} {link}" in client.get("/tasks/1").text
    assert link in client.get("/tasks/1/header").text


@pytest.mark.usefixtures("requirement")
def test_task_page_has_no_editor_link_without_the_setting(client: TestClient) -> None:
    assert "Open in editor" not in start(client)


@pytest.mark.usefixtures("requirement")
def test_task_page_has_no_editor_link_once_the_worktree_is_gone(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    configure_editor(client, settings)
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    worktree(settings).rename(tmp_path / "moved-away")
    assert "Open in editor" not in client.get("/tasks/1").text


@pytest.mark.usefixtures("requirement")
def test_no_page_load_fetches(
    client: TestClient, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    start(client)
    wait_for_status(client, 1, "waiting_for_user")
    pushed = push_commit(remote_repo, tmp_path)
    ids = {
        "repository_id": 1,
        "requirement_id": 1,
        "file_name": "bulk-user-import.md",
        "task_id": 1,
    }
    routes = client.get("/openapi.json").json()["paths"]
    pages = sorted(path.format(**ids) for path, methods in routes.items() if "get" in methods)
    page = "/repositories/1/requirements/bulk-user-import.md"
    assert {"/", "/repositories/1", "/requirements/1", page, "/tasks/1"} <= set(pages)
    for page in pages:
        assert client.get(page).status_code == 200, page
    assert run_git("rev-parse", "origin/main", cwd=checkout(settings)) != pushed
    assert not (checkout(settings) / ".git" / "FETCH_HEAD").exists()
