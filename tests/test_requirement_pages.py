"""Requirement pages: the repository page's list, and each requirement's read-only page."""

import re
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import add_requirement, run_git

REQ_1 = "specs/changes/todo/bulk-user-import.md"
PAGE = "/repositories/1/requirements/bulk-user-import.md"
LINK = f'<a href="http://testserver{PAGE}">bulk-user-import</a>'


@pytest.fixture
def registered(client: TestClient, remote_repo: Path) -> None:
    response = client.post(
        "/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"}
    )
    assert response.status_code == 200, response.text


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


def hand_made(
    settings: Settings, name: str = "bulk-user-import.md", text: str = "Import users.\n"
) -> None:
    """Write a requirement in the checkout and commit it, as its developer does."""
    add_requirement(checkout(settings), name, text)


def commit_skills(settings: Settings, *names: str) -> None:
    for name in names:
        folder = checkout(settings) / ".claude" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=checkout(settings))
    run_git("commit", "-qm", "Add skills", cwd=checkout(settings))


def configure_editor(client: TestClient, settings: Settings) -> None:
    """Give the running app an editor, as if `editor_url` had been configured."""
    app = cast("FastAPI", client.app)
    app.state.settings = settings.model_copy(update={"editor_url": "editor://open{path}/"})


def requirements_table(client: TestClient) -> str:
    """The requirements list on the repository's page, or "" when the page has none."""
    html = client.get("/repositories/1").text
    table = re.search(r'<table class="requirements">.*?</table>', html, re.DOTALL)
    return table[0] if table else ""


def section(html: str, section_id: str) -> str:
    match = re.search(rf'<section id="{section_id}".*?</section>', html, re.DOTALL)
    assert match, f"no {section_id} section"
    return match[0]


# ---------------------------------------------------------------- repository page


@pytest.mark.usefixtures("registered")
def test_repository_page_says_how_to_add_a_requirement_and_offers_no_editor(
    client: TestClient, settings: Settings
) -> None:
    html = client.get("/repositories/1").text
    assert "<h1>sample</h1>" in html
    assert f'<code>{checkout(settings)}</code> <span class="owner owner-human">' in html
    requirements = section(html, "requirements")
    assert (
        "To add a requirement, write a Markdown file in <code>specs/changes/todo</code>, "
        "named for the change, such as <code>bulk-import.md</code>, and commit it."
    ) in requirements
    empty = re.search(r'<div class="empty-state">(.*?)</div>', requirements, re.DOTALL)
    assert empty and "No requirements yet." in empty[1]
    assert "New requirement" not in html
    assert "/requirements/new" not in html


@pytest.mark.usefixtures("registered")
def test_repository_page_offers_the_checkout_in_the_editor_when_it_has_no_requirements(
    client: TestClient, settings: Settings
) -> None:
    configure_editor(client, settings)
    empty = re.search(
        r'<div class="empty-state">(.*?)</div>', client.get("/repositories/1").text, re.DOTALL
    )
    assert empty
    assert f'<a class="button primary" href="editor://open{checkout(settings)}/">' in empty[1]


@pytest.mark.usefixtures("registered")
def test_repository_list_links_each_repository_to_its_page(client: TestClient) -> None:
    assert '<a href="http://testserver/repositories/1">sample</a>' in client.get("/").text


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_requirements_with_their_state_and_no_kind(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings)
    hand_made(settings, "loose-idea.md", "No heading here.\n")
    (checkout(settings) / "specs/changes/todo/draft.md").write_text("Not committed yet.\n")
    table = requirements_table(client)
    assert f"<td>{LINK}</td>" in table
    assert "<td>active</td>" in table
    assert '<td>active <span class="badge">uncommitted</span></td>' in table
    assert "Kind" not in table and "feature" not in table
    assert "No heading here." not in table
    assert "Blocked by" not in table  # nothing waits on anything, so nothing is said of it
    html = client.get("/repositories/1").text
    assert "No requirements yet." not in html
    assert "unblocked</" not in html


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_requirements_by_file_name(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "search-notes.md")
    hand_made(settings, "audit-log.md")
    hand_made(settings)
    table = requirements_table(client)
    assert table.index(">audit-log<") < table.index(">bulk-user-import<")
    assert table.index(">bulk-user-import<") < table.index(">search-notes<")


# ---------------------------------------------------------------- a requirement's page


@pytest.mark.usefixtures("registered")
def test_requirement_page_shows_its_text_read_only(client: TestClient, settings: Settings) -> None:
    hand_made(settings, text="# An older heading\n\nImport users <from> CSV.\n")
    html = client.get(PAGE).text
    assert "<h1>bulk-user-import</h1>" in html
    text = "# An older heading\n\nImport users &lt;from&gt; CSV."
    assert f'<pre class="requirement-text">{text}</pre>' in html
    for editing in ("<textarea", 'name="body"', 'name="kind"', ">Save<", "/commit", "Commit "):
        assert editing not in html, editing
    assert "feature" not in html.partition("<main")[2]


@pytest.mark.usefixtures("registered")
def test_requirement_page_links_its_file_to_the_editor(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings)
    assert "Open in editor" not in client.get(PAGE).text
    configure_editor(client, settings)
    link = f'<a href="editor://open{checkout(settings) / REQ_1}">Open in editor</a>'
    assert link in client.get(PAGE).text


@pytest.mark.usefixtures("registered")
def test_archived_requirement_is_shown_with_a_link_to_its_archived_file(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings)
    (checkout(settings) / "specs/changes/archive").mkdir()
    archived = "specs/changes/archive/2026-10-14T150616Z-bulk-user-import.md"
    run_git("mv", REQ_1, archived, cwd=checkout(settings))
    configure_editor(client, settings)
    html = client.get(PAGE).text
    assert f"<code>{archived}</code>" in html
    assert "archived" in html
    assert '<pre class="requirement-text">Import users.</pre>' in html
    assert f'<a href="editor://open{checkout(settings) / archived}">Open in editor</a>' in html
    assert 'id="your-agent"' not in html


@pytest.mark.usefixtures("registered")
def test_requirement_page_says_to_commit_a_file_with_uncommitted_changes(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings)
    (checkout(settings) / REQ_1).write_text("Edited by hand.\n")
    html = client.get(PAGE).text
    assert "This file has uncommitted changes, which an agent working in another worktree" in html
    assert '<pre class="requirement-text">Edited by hand.</pre>' in html
    assert "<button" not in html.partition('class="notice"')[2].partition("</p>")[0]


@pytest.mark.usefixtures("registered")
def test_requirement_page_gives_the_line_that_runs_each_workflow_in_your_own_agent(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings)
    commit_skills(settings, "implement", "review-requirement")
    html = client.get(PAGE).text
    agent = section(html, "your-agent")
    assert "a branch named <code>bulk-user-import</code>" in agent
    lines = [f"/implement {REQ_1}", f"/review-requirement {REQ_1}"]
    assert re.findall(r"<pre><code>([^<]*)</code></pre>", agent) == lines
    assert "<form" not in html.partition("<main")[2].partition("</main>")[0]


@pytest.mark.usefixtures("registered")
def test_each_line_has_a_copy_button_that_shows_only_with_the_shells_script(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings)
    commit_skills(settings, "implement")
    agent = section(client.get(PAGE).text, "your-agent")
    line = f"/implement {REQ_1}"
    button = f'<button type="button" class="copy" data-copy="{line}" hidden>Copy</button>'
    assert f"<li><pre><code>{line}</code></pre> {button}</li>" in agent


@pytest.mark.usefixtures("registered")
@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/repositories/1/requirements/new"),
        ("POST", "/repositories/1/requirements"),
        ("POST", PAGE),
        ("POST", f"{PAGE}/commit"),
        ("POST", f"{PAGE}/tasks"),
        ("POST", f"{PAGE}/review"),
        ("POST", f"{PAGE}/review/address"),
        ("POST", f"{PAGE}/pull-request/open"),
    ],
)
def test_nothing_creates_edits_or_commits_a_requirement_or_starts_work_on_it(
    client: TestClient, settings: Settings, method: str, url: str
) -> None:
    hand_made(settings)
    (checkout(settings) / REQ_1).write_text("Edited by hand.\n")
    head = run_git("rev-parse", "HEAD", cwd=checkout(settings))
    form = {"name": "Other", "kind": "fix", "body": "Replaced.", "version": ""}
    response = client.request(method, url, data=form if method == "POST" else None)
    assert response.status_code in (404, 405)
    assert (checkout(settings) / REQ_1).read_text() == "Edited by hand.\n"
    assert run_git("rev-parse", "HEAD", cwd=checkout(settings)) == head
    assert not (checkout(settings) / "specs/changes/todo/other.md").exists()
    assert list(settings.worktrees_root.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    ["/repositories/999", "/repositories/999/requirements/x.md"],
)
def test_pages_for_unknown_repositories_and_requirements_are_not_found(
    client: TestClient, url: str
) -> None:
    assert client.get(url).status_code == 404


@pytest.mark.usefixtures("registered")
@pytest.mark.parametrize("file_name", ["nothing.md", "README.md", "bulk-user-import"])
def test_pages_for_files_that_are_not_requirements_are_not_found(
    client: TestClient, settings: Settings, file_name: str
) -> None:
    hand_made(settings)
    assert client.get(f"/repositories/1/requirements/{file_name}").status_code == 404


@pytest.mark.usefixtures("registered")
def test_a_requirement_whose_file_name_needs_escaping_links_to_its_own_page(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "fix #42 at 50%?.md", "Something.\n")
    page_url = "http://testserver/repositories/1/requirements/fix%20%2342%20at%2050%25%3F.md"
    link = re.search(r'<a href="([^"]*)">fix #42 at 50%\?</a>', requirements_table(client))
    assert link and link[1] == page_url
    assert "<h1>fix #42 at 50%?</h1>" in client.get(page_url).text


@pytest.mark.usefixtures("registered")
def test_a_requirement_that_cant_be_read_is_listed_as_such_and_its_page_says_why(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "search-notes.md")
    (checkout(settings) / "specs/changes/todo/latin-1.md").write_bytes(b"caf\xe9\n")
    listing = client.get("/repositories/1")
    assert listing.status_code == 200
    row = re.search(r"<tr>\s*<td><a [^>]*>latin-1</a></td>.*?</tr>", listing.text, re.DOTALL)
    assert row and "<td>can't be read</td>" in row[0]
    page = client.get("/repositories/1/requirements/latin-1.md")
    assert page.status_code == 200
    assert "latin-1.md can&#39;t be read" in page.text


# ---------------------------------------------------------------- dependencies


def needs(*names: str, text: str = "Something.") -> str:
    """A change's text that lists `names` in its depends-on."""
    listed = "".join(f"  - {name}\n" for name in names)
    return f"---\ndepends-on:\n{listed}---\n{text}\n"


def row_names(table: str) -> list[str]:
    """The names in the requirements list, in its order."""
    return re.findall(r'<td><a href="[^"]*/requirements/[^"]*">([^<]*)</a>', table)


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_requirements_in_the_order_they_can_start(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, text=needs("search-notes"))
    hand_made(settings, "export.md")
    hand_made(settings, "search-notes.md")
    hand_made(settings, "audit.md", needs("bulk-user-import", "search-notes"))
    (checkout(settings) / "specs/changes/archive").mkdir()
    run_git("mv", "specs/changes/todo/export.md", "specs/changes/archive/", cwd=checkout(settings))
    table = requirements_table(client)
    assert row_names(table) == ["search-notes", "bulk-user-import", "audit"]
    assert "rowgroup" not in table
    audit = table[table.index("audit.md") :]
    blocked_by = re.search(r"<td class=\"blocked-by\">(.*?)</td>", audit, re.DOTALL)
    assert blocked_by
    assert LINK in blocked_by[1]
    assert ">search-notes</a>" in blocked_by[1]


@pytest.mark.usefixtures("registered")
def test_repository_page_can_show_only_the_unblocked(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "search-notes.md")
    hand_made(settings, "audit.md", needs("search-notes"))
    html = client.get("/repositories/1?ready=true").text
    table = re.search(r'<table class="requirements">.*?</table>', html, re.DOTALL)
    assert table
    assert row_names(table[0]) == ["search-notes"]
    assert 'href="http://testserver/repositories/1">all</a>' in html
    assert 'ready=true">unblocked</a>' in client.get("/repositories/1").text


@pytest.mark.usefixtures("registered")
def test_repository_page_offers_the_way_out_of_the_filter_once_nothing_is_blocked(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "export.md")
    hand_made(settings, "search-notes.md")
    (checkout(settings) / "specs/changes/archive").mkdir()
    run_git("mv", "specs/changes/todo/export.md", "specs/changes/archive/", cwd=checkout(settings))
    html = client.get("/repositories/1?ready=true").text
    assert 'href="http://testserver/repositories/1">all</a> · <strong>unblocked</strong>' in html


@pytest.mark.usefixtures("registered")
def test_repository_page_shows_dependency_problems_and_lists_their_changes_apart(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "audit.md", needs("nope"))
    hand_made(settings, "report.md", needs("audit"))
    hand_made(settings, "search-notes.md")
    html = client.get("/repositories/1").text
    assert "<li>audit: needs &#34;nope&#34;, which matches no change</li>" in html
    table = requirements_table(client)
    assert row_names(table) == ["search-notes", "audit", "report"]
    held_up = """<td class="blocked-by"><span class="badge">can't be ordered</span>"""
    assert table.count(held_up) == 2


@pytest.mark.usefixtures("registered")
def test_requirement_page_shows_what_it_is_blocked_by_and_blocks(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, text=needs("search-notes", "old"))
    hand_made(settings, "export.md", needs("bulk-user-import"))
    hand_made(settings, "search-notes.md")
    archive = checkout(settings) / "specs/changes/archive"
    archive.mkdir()
    (archive / "2026-10-01T000000Z-old.md").write_text("Done.\n")
    html = client.get(PAGE).text
    blocked_by = re.search(r"<dt>Blocked by</dt>\s*<dd>(.*?)</dd>", html, re.DOTALL)
    blocks = re.search(r"<dt>Blocks</dt>\s*<dd>(.*?)</dd>", html, re.DOTALL)
    assert blocked_by and blocks
    pages = "http://testserver/repositories/1/requirements"
    assert f'<a href="{pages}/search-notes.md">search-notes</a>' in blocked_by[1]
    assert f'<a href="{pages}/old.md">old</a> (delivered)' in blocked_by[1]
    assert blocks[1].strip() == f'<a href="{pages}/export.md">export</a>'
    export = client.get(f"{pages}/export.md").text
    assert LINK in export
    assert re.search(r"<dt>Blocks</dt>\s*<dd>nothing</dd>", export)
    run_git("mv", REQ_1, str(archive), cwd=checkout(settings))
    delivered = client.get(PAGE).text
    assert f'<a href="{pages}/old.md">old</a> (delivered)' in delivered
    assert f'<a href="{pages}/export.md">export</a>' in delivered
    export = client.get(f"{pages}/export.md").text
    assert f"{LINK} (delivered)" in export


@pytest.mark.usefixtures("registered")
def test_requirement_page_shows_its_dependency_problems(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, text=needs("nope"))
    html = client.get(PAGE).text
    assert "bulk-user-import: needs &#34;nope&#34;, which matches no change" in html


@pytest.mark.usefixtures("registered")
def test_an_archived_file_linking_outside_the_checkout_delivers_nothing(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    outside = tmp_path / "old.md"
    outside.write_text("Done.\n")
    archive = checkout(settings) / "specs/changes/archive"
    archive.mkdir(parents=True)
    (archive / "2026-10-01T000000Z-old.md").symlink_to(outside)
    hand_made(settings, "audit.md", needs("old"))
    html = client.get("/repositories/1").text
    assert "<li>audit: needs &#34;old&#34;, which matches no change</li>" in html
