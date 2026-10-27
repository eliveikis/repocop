"""Requirements: Markdown files in the primary checkout, named by their files, and read-only."""

import sqlite3
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import repositories, requirements
from repocop.services.repositories import Repository
from repocop.services.requirements import Location, Requirement, RequirementError
from tests.conftest import add_requirement, run_git

TODO = Path("specs/changes/todo")


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo)).repository


def bulk_import(conn: sqlite3.Connection, settings: Settings, repo: Repository) -> Requirement:
    """bulk-user-import, written and committed in the checkout by hand."""
    add_requirement(repo.primary_path, text="Import users from CSV.\n")
    found = requirements.find(conn, settings, repo, "bulk-user-import.md")
    assert found is not None
    return found


def hand_made(
    repo: Repository,
    name: str,
    text: str = "# Search notes\n\nFaster search.\n",
    commit: bool = True,
) -> str:
    """Write a file into the requirements folder by hand; return its relative path."""
    return add_requirement(repo.primary_path, name, text, commit=commit)


# ---------------------------------------------------------------- read and detail


def test_read_returns_the_text_and_where_it_was_read(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    content = requirements.read(settings, repo, requirement)
    assert content.body == "Import users from CSV."
    assert content.path == "specs/changes/todo/bulk-user-import.md"


def test_read_keeps_an_older_changes_heading_as_part_of_its_text(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    (repo.primary_path / requirement.path).write_text("# Old title\n\nJust notes.\n")
    content = requirements.read(settings, repo, requirement)
    assert content.body == "# Old title\n\nJust notes."


def test_detail_says_whether_the_file_has_uncommitted_changes(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    assert not requirements.detail(settings, repo, requirement).uncommitted
    (repo.primary_path / requirement.path).write_text("Edited by hand.\n")
    detail = requirements.detail(settings, repo, requirement)
    assert detail.uncommitted
    assert detail.content is not None and detail.content.body == "Edited by hand."


def test_reading_a_requirement_writes_nothing_and_records_nothing(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    head = run_git("rev-parse", "HEAD", cwd=repo.primary_path)
    requirements.detail(settings, repo, requirement)
    assert run_git("rev-parse", "HEAD", cwd=repo.primary_path) == head
    assert run_git("status", "--porcelain", cwd=repo.primary_path) == ""
    assert requirements.list_for(conn, repo) == []


# ---------------------------------------------------------------- location, list


def test_location_is_active_at_its_path(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    assert requirements.location(settings, repo, requirement) is Location.ACTIVE


def test_location_is_archived_once_moved_to_the_archive_folder(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir()
    run_git("mv", requirement.path, "specs/changes/archive/", cwd=repo.primary_path)
    assert requirements.location(settings, repo, requirement) is Location.ARCHIVED
    content = requirements.read(settings, repo, requirement)
    assert content.body == "Import users from CSV."
    assert content.path == "specs/changes/archive/bulk-user-import.md"


def test_location_is_archived_under_a_name_stamped_with_when(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    (repo.primary_path / "specs/changes/archive").mkdir()
    stamped = "specs/changes/archive/2026-10-14T150616Z-bulk-user-import.md"
    run_git("mv", requirement.path, stamped, cwd=repo.primary_path)
    assert requirements.location(settings, repo, requirement) is Location.ARCHIVED
    assert requirements.read(settings, repo, requirement).path == stamped
    assert requirements.archived_path(repo.primary_path, requirement.path) == stamped


def test_archived_path_takes_the_latest_stamp_and_ignores_other_names(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir()
    for name in (
        "2026-01-01T000000Z-bulk-user-import.md",
        "2026-10-14T150616Z-bulk-user-import.md",
        "2026-10-14T150616Z-old-bulk-user-import.md",
        "draft-bulk-user-import.md",
    ):
        (archive / name).write_text("# Archived\n")
    found = requirements.archived_path(repo.primary_path, requirement.path)
    assert found == "specs/changes/archive/2026-10-14T150616Z-bulk-user-import.md"


def test_location_is_missing_when_the_file_is_gone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(conn, settings, repo)
    (repo.primary_path / requirement.path).unlink()
    assert requirements.location(settings, repo, requirement) is Location.MISSING


def test_list_for_returns_a_repositorys_recorded_requirements(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    for name in ("first.md", "second.md"):
        found = requirements.find(conn, settings, repo, Path(hand_made(repo, name)).name)
        assert found is not None
        requirements.record(conn, found)
    assert [r.name for r in requirements.list_for(conn, repo)] == ["first", "second"]


def test_get_returns_none_for_an_unknown_key(conn: sqlite3.Connection) -> None:
    assert requirements.get(conn, 999) is None


# ---------------------------------------------------------------- the folder


def test_in_folder_lists_every_markdown_file_as_a_requirement_recorded_or_not(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    recorded = requirements.record(conn, bulk_import(conn, settings, repo))
    hand_made(repo, "search-notes.md")
    hand_made(repo, "req-7-hand-made.md")
    hand_made(repo, "diagram.png")
    assert requirements.in_folder(conn, settings, repo) == [
        recorded,
        Requirement(repo.id, str(TODO / "req-7-hand-made.md")),
        Requirement(repo.id, str(TODO / "search-notes.md")),
    ]


def test_in_folder_lists_the_todo_folder_of_the_repositorys_changes_folder(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    custom = settings.model_copy(update={"changes_dir": "docs/rfcs"})
    repo = repositories.register(conn, custom, str(remote_repo)).repository
    add_requirement(repo.primary_path, "faster-search.md", folder="docs/rfcs/todo")
    add_requirement(repo.primary_path, "elsewhere.md")
    assert requirements.in_folder(conn, custom, repo) == [
        Requirement(repo.id, "docs/rfcs/todo/faster-search.md")
    ]


def test_in_folder_is_empty_without_a_requirements_folder(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    assert requirements.in_folder(conn, settings, repo) == []


def test_in_folder_lists_a_link_without_following_it(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("Not the repository's\n")
    (repo.primary_path / TODO).mkdir(parents=True, exist_ok=True)
    (repo.primary_path / TODO / "link.md").symlink_to(secret)
    [listed] = requirements.in_folder(conn, settings, repo)
    assert listed.path == str(TODO / "link.md")
    with pytest.raises(RequirementError, match="outside"):
        requirements.read(settings, repo, listed)


def test_in_folder_refuses_a_requirements_folder_outside_the_checkout(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / "changes" / "todo").mkdir(parents=True)
    (outside / "changes" / "todo" / "secret.md").write_text("Not the repository's\n")
    (repo.primary_path / "specs").symlink_to(outside)
    with pytest.raises(RequirementError, match="outside"):
        requirements.in_folder(conn, settings, repo)


# ---------------------------------------------------------------- find and record


def test_find_returns_a_hand_made_file_not_recorded_yet(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    path = hand_made(repo, "search-notes.md")
    found = requirements.find(conn, settings, repo, "search-notes.md")
    assert found == Requirement(repo.id, path, None)
    assert found is not None and found.name == "search-notes"
    assert requirements.list_for(conn, repo) == []


def test_find_returns_a_recorded_requirement_with_its_key(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    recorded = requirements.record(conn, bulk_import(conn, settings, repo))
    assert recorded.id is not None
    assert requirements.find(conn, settings, repo, "bulk-user-import.md") == recorded


def test_find_returns_a_requirement_recorded_under_an_id_by_its_file_name(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    path = hand_made(repo, "req-7-hand-made.md")
    conn.execute(
        "INSERT INTO requirements (id, repository_id, path, created_at, updated_at)"
        " VALUES (7, ?, ?, '', '')",
        (repo.id, path),
    )
    found = requirements.find(conn, settings, repo, "req-7-hand-made.md")
    assert found == Requirement(repo.id, path, 7)


def test_find_returns_an_archived_change_by_its_name_before_the_stamp(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir(parents=True)
    (archive / "2026-10-14T150616Z-delivered.md").write_text("Done.\n")
    found = requirements.find(conn, settings, repo, "delivered.md")
    assert found is not None
    assert requirements.location(settings, repo, found) is Location.ARCHIVED


@pytest.mark.parametrize(
    "file_name", ["nothing-here.md", "search-notes", "../../README.md", "README.md", ".md", ""]
)
def test_find_returns_none_for_anything_but_a_requirements_file(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, file_name: str
) -> None:
    hand_made(repo, "search-notes.md")
    assert requirements.find(conn, settings, repo, file_name) is None


def test_record_records_a_requirement_once(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    hand_made(repo, "search-notes.md")
    found = requirements.find(conn, settings, repo, "search-notes.md")
    assert found is not None
    recorded = requirements.record(conn, found)
    assert recorded.id is not None
    assert requirements.record(conn, found) == recorded
    assert requirements.list_for(conn, repo) == [recorded]


def test_record_keeps_only_references_in_the_database(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    recorded = requirements.record(conn, bulk_import(conn, settings, repo))
    row = dict(conn.execute("SELECT * FROM requirements").fetchone())
    assert set(row) == {"id", "repository_id", "path", "created_at", "updated_at"}
    assert (row["id"], row["repository_id"], row["path"]) == (
        recorded.id,
        repo.id,
        "specs/changes/todo/bulk-user-import.md",
    )
