"""The shell every page shares: the sidebar with the repositories, the scripts, the breadcrumbs,
the quick switcher, section links, confirmations as toasts, and relative times."""

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import add_requirement, run_git

REQUIREMENT_PAGE = "/repositories/1/requirements/bulk-user-import.md"


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


@pytest.fixture
def requirement(client: TestClient, settings: Settings, remote_repo: Path) -> None:
    """Repository `sample` with a committed skill, and bulk-user-import committed in its
    checkout."""
    client.post("/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"})
    folder = checkout(settings) / ".claude" / "skills" / "implement"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# implement\n")
    run_git("add", ".claude", cwd=checkout(settings))
    run_git("commit", "-qm", "Add skills", cwd=checkout(settings))
    add_requirement(checkout(settings))


def sync(client: TestClient) -> None:
    """Template sync #1, completed."""
    response = client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    assert response.status_code == 200, response.text


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


PAGES = ["/", "/repositories/1", "/repositories/1/sync", REQUIREMENT_PAGE, "/tasks/1"]


@pytest.mark.usefixtures("requirement")
def test_every_page_has_a_sidebar_with_the_repositories_and_nothing_else(
    client: TestClient,
) -> None:
    sync(client)
    for page in PAGES:
        nav = sidebar(client.get(page).text)
        assert '<a href="http://testserver/repositories/1"' in nav, page
        assert re.findall(r'<h2 class="nav-heading"[^>]*>([^<]*)</h2>', nav) == ["Repositories"]
        assert "hx-get" not in nav, page


@pytest.mark.usefixtures("requirement")
def test_every_page_loads_only_the_vendored_htmx_and_the_shell_script(client: TestClient) -> None:
    sync(client)
    for page in PAGES:
        html = client.get(page).text
        scripts = re.findall(
            r'<script src="http://testserver(/static/[^"]+)" defer></script>', html
        )
        assert scripts == ["/static/vendor/htmx.min.js", "/static/js/shell.js"], page
        assert html.count("<script") == len(scripts), page
    for path in scripts:
        script = client.get(path)
        assert script.status_code == 200
        assert "javascript" in script.headers["content-type"]


# ---------------------------------------------------------------- breadcrumbs


@pytest.mark.usefixtures("requirement")
def test_breadcrumbs_show_where_a_page_is_and_link_each_part(client: TestClient) -> None:
    html = client.get(REQUIREMENT_PAGE).text
    crumbs = re.search(r'<nav class="breadcrumbs" aria-label="Breadcrumb">(.*?)</nav>', html, re.S)
    assert crumbs, "no breadcrumbs"
    assert re.findall(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', crumbs[1]) == [
        ("http://testserver/", "Repositories"),
        ("http://testserver/repositories/1", "sample"),
        (f"http://testserver{REQUIREMENT_PAGE}", "bulk-user-import"),
    ]
    assert 'aria-current="page">bulk-user-import</a>' in crumbs[1]
    assert 'class="breadcrumbs"' not in client.get("/").text


# ---------------------------------------------------------------- quick switcher


@pytest.mark.usefixtures("requirement")
def test_switcher_offers_nothing_before_anything_is_typed(client: TestClient) -> None:
    sync(client)
    assert options(client, "") == []
    assert "Type to find" in client.get("/navigation/matches").text
    assert 'hx-get="http://testserver/navigation/matches"' in client.get("/").text


@pytest.mark.usefixtures("requirement")
def test_switcher_finds_repositories_requirements_and_template_syncs(
    client: TestClient, settings: Settings
) -> None:
    sync(client)
    (checkout(settings) / "specs/changes/todo/search-notes.md").write_text("Faster search.\n")
    pages = "http://testserver/repositories/1/requirements"
    assert options(client, "SAM") == ["http://testserver/repositories/1"]
    assert options(client, "search") == [f"{pages}/search-notes.md"]  # on disk, not committed
    assert options(client, "bulk") == [f"{pages}/bulk-user-import.md"]
    assert options(client, "#1") == ["http://testserver/tasks/1"]
    assert options(client, "agent/template-sync") == ["http://testserver/tasks/1"]
    assert options(client, "nothing like it") == []


def test_switcher_escapes_what_was_typed(client: TestClient) -> None:
    html = client.get("/navigation/matches", params={"q": "<b>x</b>"}).text
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


# ---------------------------------------------------------------- section links


@pytest.mark.usefixtures("requirement")
def test_section_links_lead_to_sections_of_their_page(client: TestClient) -> None:
    sync(client)
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
    client.post("/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"})
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
    sync(client)
    created = (datetime.now(UTC) - timedelta(minutes=3, seconds=5)).replace(microsecond=0)
    with sqlite3.connect(settings.database_path) as raw:
        raw.execute("UPDATE tasks SET created_at = ? WHERE id = 1", (created.isoformat(),))
    exact = created.strftime("%Y-%m-%d %H:%M:%S UTC")
    shown = f'<time datetime="{created.isoformat()}" title="{exact}">3 min ago</time>'
    assert shown in client.get("/tasks/1").text
    assert shown in client.get("/repositories/1").text
