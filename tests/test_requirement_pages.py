"""Requirement pages: the repository page, creating, editing and committing requirements."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop import db
from repocop.config import Settings
from tests.conftest import run_git

REQ_1 = "specs/changes/todo/bulk-user-import.md"
PAGE = "/repositories/1/requirements/bulk-user-import.md"
LINK = f'<a href="http://testserver{PAGE}">bulk-user-import</a>'


@pytest.fixture
def registered(client: TestClient, remote_repo: Path) -> None:
    response = client.post("/repositories", data={"remote_url": str(remote_repo)})
    assert response.status_code == 200, response.text


def create(
    client: TestClient,
    name: str = "Bulk user import",
    body: str = "Import users.",
    kind: str = "feature",
) -> str:
    """Post the New requirement form and return the page it redirects to."""
    response = client.post(
        "/repositories/1/requirements",
        data={"name": name, "kind": kind, "body": body},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return client.get(response.headers["location"]).text


def version(html: str) -> str:
    match = re.search(r'name="version" value="([0-9a-f]+)"', html)
    assert match, "no version field"
    return match[1]


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


# ---------------------------------------------------------------- repository page


@pytest.mark.usefixtures("registered")
def test_repository_page_shows_the_repository_and_a_new_requirement_link(
    client: TestClient, settings: Settings
) -> None:
    html = client.get("/repositories/1").text
    assert "<h1>sample</h1>" in html
    assert f'<code>{checkout(settings)}</code> <span class="owner owner-human">' in html
    new = 'href="http://testserver/repositories/1/requirements/new">New requirement</a>'
    empty = re.search(r'<div class="empty-state">(.*?)</div>', html, re.DOTALL)
    assert empty, "no empty state"
    assert "No requirements yet." in empty[1]
    assert new in empty[1]


@pytest.mark.usefixtures("registered")
def test_repository_list_links_each_repository_to_its_page(client: TestClient) -> None:
    assert '<a href="http://testserver/repositories/1">sample</a>' in client.get("/").text


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_requirements_with_kind_and_state(client: TestClient) -> None:
    create(client, kind="fix")
    html = client.get("/repositories/1").text
    assert f"<td>{LINK}</td>" in html
    assert "<td>fix</td>" in html
    assert "<td>active</td>" in html


# ---------------------------------------------------------------- create


@pytest.mark.usefixtures("registered")
def test_new_requirement_form_offers_name_kind_and_a_large_editor(client: TestClient) -> None:
    html = client.get("/repositories/1/requirements/new").text
    assert 'name="name"' in html
    assert 'type="radio" name="kind" value="feature" checked' in html
    assert 'type="radio" name="kind" value="fix"' in html
    assert re.search(r'<textarea name="body" rows="(\d+)"', html)


@pytest.mark.usefixtures("registered")
def test_create_requirement_saves_commits_and_opens_it(
    client: TestClient, settings: Settings
) -> None:
    html = create(client)
    assert "<h1>bulk-user-import</h1>" in html
    assert "Saved and committed." in html
    assert ">Import users.</textarea>" in html
    assert 'name="name"' not in html  # the name is fixed once the file is named
    assert (checkout(settings) / REQ_1).read_text() == "Import users.\n"  # no title heading
    assert run_git("status", "--porcelain", cwd=checkout(settings)) == ""


@pytest.mark.usefixtures("registered")
def test_create_requirement_keeps_long_text_intact(client: TestClient, settings: Settings) -> None:
    body = "\n\n".join(f"Paragraph {n}: " + "detail " * 60 for n in range(8))
    create(client, body=body)
    assert (checkout(settings) / REQ_1).read_text() == f"{body}\n"


@pytest.mark.usefixtures("registered")
def test_create_requirement_shows_errors_inline_and_keeps_the_input(client: TestClient) -> None:
    response = client.post(
        "/repositories/1/requirements", data={"name": "", "kind": "fix", "body": "keep me"}
    )
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert ">keep me</textarea>" in response.text
    assert 'value="fix" checked' in response.text


@pytest.mark.usefixtures("registered")
def test_create_requirement_in_a_missing_checkout_says_why(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    checkout(settings).rename(tmp_path / "moved-away")
    response = client.post(
        "/repositories/1/requirements", data={"name": "X", "kind": "feature", "body": ""}
    )
    assert response.status_code == 400
    assert "isn&#39;t there" in response.text


# ---------------------------------------------------------------- edit and commit


@pytest.mark.usefixtures("registered")
def test_save_requirement_updates_and_commits_it(client: TestClient, settings: Settings) -> None:
    page = create(client)
    response = client.post(
        PAGE,
        data={"kind": "feature", "body": "New.", "version": version(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "<h1>bulk-user-import</h1>" in html
    assert "Saved and committed." in html
    assert (checkout(settings) / REQ_1).read_text() == "New.\n"


@pytest.mark.usefixtures("registered")
def test_save_requirement_refuses_a_file_changed_elsewhere_and_keeps_the_input(
    client: TestClient, settings: Settings
) -> None:
    page = create(client)
    (checkout(settings) / REQ_1).write_text("# Edited in my editor\n")
    response = client.post(
        PAGE,
        data={"kind": "feature", "body": "my text", "version": version(page)},
    )
    assert response.status_code == 400
    assert "changed on disk" in response.text
    assert ">my text</textarea>" in response.text
    assert (checkout(settings) / REQ_1).read_text() == "# Edited in my editor\n"


@pytest.mark.usefixtures("registered")
def test_save_requirement_on_a_detached_head_says_why(
    client: TestClient, settings: Settings
) -> None:
    page = create(client)
    run_git("checkout", "-q", "--detach", cwd=checkout(settings))
    response = client.post(
        PAGE,
        data={"kind": "feature", "body": "Changed.", "version": version(page)},
    )
    assert response.status_code == 400
    assert "detached HEAD" in response.text


@pytest.mark.usefixtures("registered")
def test_requirement_page_offers_to_commit_uncommitted_changes(
    client: TestClient, settings: Settings
) -> None:
    create(client)
    (checkout(settings) / REQ_1).write_text("# Bulk user import\n\nEdited by hand.\n")
    html = client.get(PAGE).text
    assert "uncommitted changes" in html
    assert f'action="http://testserver{PAGE}/commit"' in html
    response = client.post(f"{PAGE}/commit", follow_redirects=False)
    assert response.status_code == 303
    html = client.get(response.headers["location"]).text
    assert "Committed." in html
    assert f'action="http://testserver{PAGE}/commit"' not in html


@pytest.mark.usefixtures("registered")
def test_commit_with_nothing_to_commit_says_so(client: TestClient) -> None:
    create(client)
    response = client.post(f"{PAGE}/commit")
    assert response.status_code == 400
    assert "nothing to commit" in response.text


@pytest.mark.usefixtures("registered")
def test_archived_requirement_is_shown_read_only(client: TestClient, settings: Settings) -> None:
    create(client)
    (checkout(settings) / "specs/changes/archive").mkdir()
    run_git("mv", REQ_1, "specs/changes/archive/", cwd=checkout(settings))
    html = client.get(PAGE).text
    assert "archived" in html
    assert "<pre>Import users.</pre>" in html
    assert 'name="version"' not in html


@pytest.mark.usefixtures("registered")
def test_missing_requirement_file_is_reported(client: TestClient, settings: Settings) -> None:
    create(client)
    (checkout(settings) / REQ_1).unlink()
    html = client.get(PAGE).text
    assert "missing" in html
    assert 'name="version"' not in html


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/repositories/999"),
        ("GET", "/repositories/999/requirements/new"),
        ("POST", "/repositories/999/requirements"),
        ("GET", "/requirements/999"),
        ("GET", "/repositories/999/requirements/x.md"),
        ("POST", "/repositories/999/requirements/x.md"),
        ("POST", "/repositories/999/requirements/x.md/commit"),
    ],
)
def test_pages_for_unknown_repositories_and_requirements_are_not_found(
    client: TestClient, method: str, url: str
) -> None:
    assert client.request(method, url).status_code == 404


@pytest.mark.usefixtures("registered")
@pytest.mark.parametrize("file_name", ["nothing.md", "README.md", "bulk-user-import"])
def test_pages_for_files_that_are_not_requirements_are_not_found(
    client: TestClient, file_name: str
) -> None:
    create(client)
    assert client.get(f"/repositories/1/requirements/{file_name}").status_code == 404
    assert client.post(f"/repositories/1/requirements/{file_name}/commit").status_code == 404


@pytest.mark.usefixtures("registered")
def test_a_requirements_page_recorded_under_a_number_is_found_by_it(client: TestClient) -> None:
    create(client)
    response = client.get("/requirements/1", follow_redirects=False)
    assert response.headers["location"] == f"http://testserver{PAGE}"


@pytest.mark.usefixtures("registered")
def test_create_requirement_refuses_a_name_already_used_and_keeps_the_input(
    client: TestClient, settings: Settings
) -> None:
    create(client, body="The first one.")
    response = client.post(
        "/repositories/1/requirements",
        data={"name": "Bulk user import", "kind": "feature", "body": "keep me"},
    )
    assert response.status_code == 400
    assert "bulk-user-import is already the name of a requirement" in response.text
    assert ">keep me</textarea>" in response.text
    assert (checkout(settings) / REQ_1).read_text() == "The first one.\n"


# ---------------------------------------------------------------- hand-made files


def hand_made(
    settings: Settings, name: str, text: str = "# Search notes\n\nFaster search.\n"
) -> None:
    folder = checkout(settings) / "specs/changes/todo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text)
    run_git("add", ".", cwd=checkout(settings))
    run_git("commit", "-qm", f"Add {name}", cwd=checkout(settings))


def requirements_table(client: TestClient) -> str:
    """The requirements list on the repository's page, or "" when the page has none."""
    html = client.get("/repositories/1").text
    table = re.search(r'<table class="requirements">.*?</table>', html, re.DOTALL)
    return table[0] if table else ""


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_a_hand_made_file_as_a_requirement(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "search-notes.md")
    table = requirements_table(client)
    page = "http://testserver/repositories/1/requirements/search-notes.md"
    assert f'<td><a href="{page}">search-notes</a></td>' in table
    assert "<td>active</td>" in table
    assert "Assign ID" not in table and "Track" not in table
    html = client.get("/repositories/1").text
    assert "No requirements yet." not in html
    assert "Every Markdown file in <code>specs/changes/todo</code> is a requirement" in html
    assert "Blocked by" not in table  # nothing waits on anything, so nothing is said of it
    assert "unblocked</" not in html


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_created_and_hand_made_requirements_by_file_name(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "search-notes.md")
    hand_made(settings, "audit-log.md")
    create(client)
    table = requirements_table(client)
    assert table.index(">audit-log<") < table.index(">bulk-user-import<")
    assert table.index(">bulk-user-import<") < table.index(">search-notes<")


@pytest.mark.usefixtures("registered")
def test_repository_page_lists_a_hand_made_file_without_its_text(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "loose-idea.md", "No heading here.\n")
    table = requirements_table(client)
    assert ">loose-idea</a>" in table
    assert "No heading here." not in table


@pytest.mark.usefixtures("registered")
def test_a_hand_made_files_page_opens_by_its_file_name_and_records_nothing(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "search-notes.md")
    html = client.get("/repositories/1/requirements/search-notes.md").text
    assert "<h1>search-notes</h1>" in html
    assert "Faster search.</textarea>" in html
    with db.connect(settings.database_path) as conn:
        assert conn.execute("SELECT count(*) FROM requirements").fetchone()[0] == 0


@pytest.mark.usefixtures("registered")
def test_saving_a_hand_made_files_kind_records_it(client: TestClient, settings: Settings) -> None:
    hand_made(settings, "search-notes.md")
    page = "/repositories/1/requirements/search-notes.md"
    html = client.get(page).text
    body = "# Search notes\n\nFaster search."
    response = client.post(
        page, data={"kind": "fix", "body": body, "version": version(html)}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "· fix" in client.get(response.headers["location"]).text
    with db.connect(settings.database_path) as conn:
        assert [tuple(row) for row in conn.execute("SELECT path, kind FROM requirements")] == [
            ("specs/changes/todo/search-notes.md", "fix")
        ]


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
    create(client, name="Bulk user import", body=needs("search-notes"))
    create(client, name="Export")
    hand_made(settings, "search-notes.md")
    hand_made(settings, "audit.md", needs("bulk-user-import", "search-notes"))
    (checkout(settings) / "specs/changes/archive").mkdir()
    run_git("mv", "specs/changes/todo/export.md", "specs/changes/archive/", cwd=checkout(settings))
    table = requirements_table(client)
    assert row_names(table) == ["search-notes", "bulk-user-import", "audit", "export"]
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
    create(client, name="Export")
    hand_made(settings, "search-notes.md")
    (checkout(settings) / "specs/changes/archive").mkdir()
    run_git("mv", "specs/changes/todo/export.md", "specs/changes/archive/", cwd=checkout(settings))
    html = client.get("/repositories/1?ready=true").text  # it still hides the delivered export
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
    create(client, name="Bulk user import", body=needs("search-notes", "old"))
    create(client, name="Export", body=needs("bulk-user-import"))
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
def test_requirement_page_shows_its_dependency_problems(client: TestClient) -> None:
    create(client, body=needs("nope"))
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


@pytest.mark.usefixtures("registered")
def test_a_requirement_whose_file_name_needs_escaping_links_to_its_own_page(
    client: TestClient, settings: Settings
) -> None:
    hand_made(settings, "fix #42 at 50%?.md", "Something.\n")
    page_url = "http://testserver/repositories/1/requirements/fix%20%2342%20at%2050%25%3F.md"
    link = re.search(r'<a href="([^"]*)">fix #42 at 50%\?</a>', requirements_table(client))
    assert link and link[1] == page_url
    page = client.get(page_url).text
    assert "<h1>fix #42 at 50%?</h1>" in page
    action = re.search(r'<form class="requirement" method="post" action="([^"]*)"', page)
    assert action and action[1] == page_url
    response = client.post(
        page_url,
        data={"kind": "feature", "body": "Changed.", "version": version(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].split("?")[0] == page_url


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
