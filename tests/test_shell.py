"""The shell every page shares: the sidebar with the repositories and the active tasks, the
breadcrumbs, the quick switcher, section links, confirmations as toasts, and relative times."""

import re
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import run_git

REQUIREMENT_PAGE = "/repositories/1/requirements/bulk-user-import.md"


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


@pytest.fixture
def requirement(client: TestClient, settings: Settings, remote_repo: Path) -> None:
    """Repository `sample` with a committed skill, and bulk-user-import created through the UI."""
    client.post("/repositories", data={"remote_url": str(remote_repo)})
    folder = checkout(settings) / ".claude" / "skills" / "implement"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# implement\n")
    run_git("add", ".claude", cwd=checkout(settings))
    run_git("commit", "-qm", "Add skills", cwd=checkout(settings))
    client.post(
        "/repositories/1/requirements",
        data={"name": "Bulk user import", "kind": "feature", "body": "Import users."},
    )


def start_task(client: TestClient) -> None:
    """Start task #1 on bulk-user-import, and wait until its first turn has ended."""
    response = client.post(
        f"{REQUIREMENT_PAGE}/tasks", data={"workflow": "implement"}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    deadline = time.monotonic() + 5.0
    while "status-waiting_for_user" not in client.get("/tasks/1/header").text:
        if time.monotonic() > deadline:
            raise AssertionError("task #1 never waited for the user")
        time.sleep(0.02)


def sidebar(html: str) -> str:
    match = re.search(r'<nav id="sidebar".*?</nav>', html, re.DOTALL)
    assert match, "no sidebar"
    return match[0]


def toasts(html: str) -> str:
    match = re.search(r'<div class="toasts" role="status">(.*?)</div>', html, re.DOTALL)
    assert match, "no toast region"
    return match[1]


def options(client: TestClient, query: str) -> list[str]:
    """Where each of the quick switcher's options for `query` leads, in order."""
    html = client.get("/navigation/matches", params={"q": query}).text
    return re.findall(r'<a role="option"[^>]* href="([^"]*)"', html)


# ---------------------------------------------------------------- sidebar


@pytest.mark.usefixtures("requirement")
def test_every_page_has_a_sidebar_with_the_repositories_and_the_active_tasks(
    client: TestClient,
) -> None:
    start_task(client)
    pages = [
        "/",
        "/repositories/1",
        "/repositories/1/sync",
        "/repositories/1/requirements/new",
        REQUIREMENT_PAGE,
        "/tasks/1",
    ]
    for page in pages:
        nav = sidebar(client.get(page).text)
        assert '<a href="http://testserver/repositories/1"' in nav, page
        entry = re.search(
            r'<li><a id="active-task-1" href="http://testserver/tasks/1">.*?</li>', nav, re.DOTALL
        )
        assert entry, page
        assert '<span class="status status-waiting_for_user">waiting_for_user</span>' in entry[0]
        assert "sample" in entry[0]


@pytest.mark.usefixtures("requirement")
def test_sidebar_refreshes_its_active_tasks_while_one_is_active_and_stops_after(
    client: TestClient,
) -> None:
    start_task(client)
    polling = 'hx-get="http://testserver/navigation/active-tasks" hx-trigger="every 2s"'
    assert polling in sidebar(client.get("/").text)
    assert 'href="http://testserver/tasks/1"' in client.get("/navigation/active-tasks").text
    client.post("/tasks/1/cancel")
    fragment = client.get("/navigation/active-tasks").text
    assert "hx-trigger" not in fragment
    assert "tasks/1" not in fragment
    assert "hx-trigger" not in sidebar(client.get("/").text)


@pytest.mark.usefixtures("requirement")
def test_sidebar_reads_only_the_database(
    client: TestClient, git_calls: Callable[[], list[list[str]]]
) -> None:
    start_task(client)
    before = len(git_calls())
    assert "active-task-1" in client.get("/navigation/active-tasks").text
    assert len(git_calls()) == before


# ---------------------------------------------------------------- breadcrumbs


@pytest.mark.usefixtures("requirement")
def test_breadcrumbs_show_where_a_page_is_and_link_each_part(client: TestClient) -> None:
    start_task(client)
    html = client.get("/tasks/1").text
    crumbs = re.search(r'<nav class="breadcrumbs" aria-label="Breadcrumb">(.*?)</nav>', html, re.S)
    assert crumbs, "no breadcrumbs"
    assert re.findall(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', crumbs[1]) == [
        ("http://testserver/", "Repositories"),
        ("http://testserver/repositories/1", "sample"),
        (f"http://testserver{REQUIREMENT_PAGE}", "bulk-user-import"),
        ("http://testserver/tasks/1", "Task #1"),
    ]
    assert 'aria-current="page">Task #1</a>' in crumbs[1]
    assert 'class="breadcrumbs"' not in client.get("/").text


# ---------------------------------------------------------------- quick switcher


@pytest.mark.usefixtures("requirement")
def test_switcher_lists_the_active_tasks_before_anything_is_typed(client: TestClient) -> None:
    assert options(client, "") == []
    start_task(client)
    assert options(client, "") == ["http://testserver/tasks/1"]
    assert 'hx-get="http://testserver/navigation/matches"' in client.get("/").text


@pytest.mark.usefixtures("requirement")
def test_switcher_finds_repositories_requirements_and_tasks(
    client: TestClient, settings: Settings
) -> None:
    start_task(client)
    (checkout(settings) / "specs/changes/todo/search-notes.md").write_text("Faster search.\n")
    pages = "http://testserver/repositories/1/requirements"
    assert options(client, "SAM") == ["http://testserver/repositories/1"]
    assert options(client, "search") == [f"{pages}/search-notes.md"]  # on disk, not recorded
    assert options(client, "bulk") == [f"{pages}/bulk-user-import.md", "http://testserver/tasks/1"]
    assert options(client, "#1") == ["http://testserver/tasks/1"]
    assert options(client, "agent/bulk-user") == [
        f"{pages}/bulk-user-import.md",
        "http://testserver/tasks/1",
    ]
    assert options(client, "nothing like it") == []


def test_switcher_escapes_what_was_typed(client: TestClient) -> None:
    html = client.get("/navigation/matches", params={"q": "<b>x</b>"}).text
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


# ---------------------------------------------------------------- section links


@pytest.mark.usefixtures("requirement")
def test_section_links_lead_to_sections_of_their_page(client: TestClient) -> None:
    start_task(client)
    for page in ("/repositories/1", "/tasks/1"):
        html = client.get(page).text
        nav = re.search(
            r'<nav class="section-links" aria-label="On this page">(.*?)</nav>', html, re.S
        )
        assert nav, page
        targets = re.findall(r'href="#([^"]+)"', nav[1])
        assert len(targets) >= 3, page
        for target in targets:
            assert f'id="{target}"' in html, f"{page}: #{target}"


# ---------------------------------------------------------------- toasts and errors


def test_a_confirmation_is_a_toast_and_an_error_stays_inline(
    client: TestClient, remote_repo: Path
) -> None:
    client.post("/repositories", data={"remote_url": str(remote_repo)})
    fetched = client.post("/repositories/1/fetch").text
    assert '<p class="toast">Fetched from origin.</p>' in toasts(fetched)
    refused = client.post("/repositories", data={"remote_url": "-x"})
    assert refused.status_code == 400
    assert toasts(refused.text).strip() == ""
    assert '<p class="error" role="alert">' in refused.text.partition("<main")[2]


# ---------------------------------------------------------------- times


@pytest.mark.usefixtures("requirement")
def test_times_read_as_relative_with_the_exact_time_on_hover(
    client: TestClient, settings: Settings
) -> None:
    start_task(client)
    created = (datetime.now(UTC) - timedelta(minutes=3, seconds=5)).replace(microsecond=0)
    with sqlite3.connect(settings.database_path) as raw:
        raw.execute("UPDATE tasks SET created_at = ? WHERE id = 1", (created.isoformat(),))
    exact = created.strftime("%Y-%m-%d %H:%M:%S UTC")
    shown = f'<time datetime="{created.isoformat()}" title="{exact}">3 min ago</time>'
    assert shown in client.get("/tasks/1").text
    assert shown in client.get(REQUIREMENT_PAGE).text
