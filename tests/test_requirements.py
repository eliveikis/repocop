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
    return repositories.register(conn, settings, str(remote_repo), default_branch="main").repository


def bulk_import(settings: Settings, repo: Repository) -> Requirement:
    """bulk-user-import, written and committed in the checkout by hand."""
    add_requirement(repo.primary_path, text="Import users from CSV.\n")
    found = requirements.find(settings, repo, "bulk-user-import.md")
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


def test_read_returns_the_text_and_where_it_was_read(settings: Settings, repo: Repository) -> None:
    requirement = bulk_import(settings, repo)
    content = requirements.read(settings, repo, requirement)
    assert content.body == "Import users from CSV."
    assert content.path == "specs/changes/todo/bulk-user-import.md"


def test_read_keeps_an_older_changes_heading_as_part_of_its_text(
    settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(settings, repo)
    (repo.primary_path / requirement.path).write_text("# Old title\n\nJust notes.\n")
    content = requirements.read(settings, repo, requirement)
    assert content.body == "# Old title\n\nJust notes."


def test_detail_says_whether_the_file_has_uncommitted_changes(
    settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(settings, repo)
    assert not requirements.detail(settings, repo, requirement).uncommitted
    (repo.primary_path / requirement.path).write_text("Edited by hand.\n")
    detail = requirements.detail(settings, repo, requirement)
    assert detail.uncommitted
    assert detail.content is not None and detail.content.body == "Edited by hand."


def test_reading_a_requirement_writes_nothing(settings: Settings, repo: Repository) -> None:
    requirement = bulk_import(settings, repo)
    head = run_git("rev-parse", "HEAD", cwd=repo.primary_path)
    requirements.detail(settings, repo, requirement)
    assert run_git("rev-parse", "HEAD", cwd=repo.primary_path) == head
    assert run_git("status", "--porcelain", cwd=repo.primary_path) == ""


# ---------------------------------------------------------------- location, list


def test_location_is_active_at_its_path(settings: Settings, repo: Repository) -> None:
    requirement = bulk_import(settings, repo)
    assert requirements.location(settings, repo, requirement) is Location.ACTIVE


def test_location_is_archived_once_moved_to_the_archive_folder(
    settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(settings, repo)
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir()
    run_git("mv", requirement.path, "specs/changes/archive/", cwd=repo.primary_path)
    assert requirements.location(settings, repo, requirement) is Location.ARCHIVED
    content = requirements.read(settings, repo, requirement)
    assert content.body == "Import users from CSV."
    assert content.path == "specs/changes/archive/bulk-user-import.md"


def test_location_is_archived_under_a_name_stamped_with_when(
    settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(settings, repo)
    (repo.primary_path / "specs/changes/archive").mkdir()
    stamped = "specs/changes/archive/2026-10-14T150616Z-bulk-user-import.md"
    run_git("mv", requirement.path, stamped, cwd=repo.primary_path)
    assert requirements.location(settings, repo, requirement) is Location.ARCHIVED
    assert requirements.read(settings, repo, requirement).path == stamped
    assert requirements.archived_path(repo.primary_path, requirement.path) == stamped


def test_archived_path_takes_the_latest_stamp_and_ignores_other_names(
    settings: Settings, repo: Repository
) -> None:
    requirement = bulk_import(settings, repo)
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


def test_location_is_missing_when_the_file_is_gone(settings: Settings, repo: Repository) -> None:
    requirement = bulk_import(settings, repo)
    (repo.primary_path / requirement.path).unlink()
    assert requirements.location(settings, repo, requirement) is Location.MISSING


# ---------------------------------------------------------------- the folder


def test_in_folder_lists_every_markdown_file_as_a_requirement(
    settings: Settings, repo: Repository
) -> None:
    found = bulk_import(settings, repo)
    hand_made(repo, "search-notes.md")
    hand_made(repo, "req-7-hand-made.md")
    hand_made(repo, "diagram.png")
    assert requirements.in_folder(settings, repo) == [
        found,
        Requirement(repo.id, str(TODO / "req-7-hand-made.md")),
        Requirement(repo.id, str(TODO / "search-notes.md")),
    ]


def test_in_folder_lists_the_todo_folder_of_the_repositorys_changes_folder(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    custom = settings.model_copy(update={"changes_dir": "docs/rfcs"})
    repo = repositories.register(conn, custom, str(remote_repo), default_branch="main").repository
    add_requirement(repo.primary_path, "faster-search.md", folder="docs/rfcs/todo")
    add_requirement(repo.primary_path, "elsewhere.md")
    assert requirements.in_folder(custom, repo) == [
        Requirement(repo.id, "docs/rfcs/todo/faster-search.md")
    ]


def test_in_folder_is_empty_without_a_requirements_folder(
    settings: Settings, repo: Repository
) -> None:
    assert requirements.in_folder(settings, repo) == []


def test_in_folder_lists_a_link_without_following_it(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("Not the repository's\n")
    (repo.primary_path / TODO).mkdir(parents=True, exist_ok=True)
    (repo.primary_path / TODO / "link.md").symlink_to(secret)
    [listed] = requirements.in_folder(settings, repo)
    assert listed.path == str(TODO / "link.md")
    with pytest.raises(RequirementError, match="outside"):
        requirements.read(settings, repo, listed)


def test_in_folder_refuses_a_requirements_folder_outside_the_checkout(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / "changes" / "todo").mkdir(parents=True)
    (outside / "changes" / "todo" / "secret.md").write_text("Not the repository's\n")
    (repo.primary_path / "specs").symlink_to(outside)
    with pytest.raises(RequirementError, match="outside"):
        requirements.in_folder(settings, repo)


# ---------------------------------------------------------------- find


def test_find_returns_a_hand_made_file(settings: Settings, repo: Repository) -> None:
    path = hand_made(repo, "search-notes.md")
    found = requirements.find(settings, repo, "search-notes.md")
    assert found == Requirement(repo.id, path)
    assert found is not None and found.name == "search-notes"


def test_find_returns_an_archived_change_by_its_name_before_the_stamp(
    settings: Settings, repo: Repository
) -> None:
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir(parents=True)
    (archive / "2026-10-14T150616Z-delivered.md").write_text("Done.\n")
    found = requirements.find(settings, repo, "delivered.md")
    assert found is not None
    assert requirements.location(settings, repo, found) is Location.ARCHIVED


@pytest.mark.parametrize(
    "file_name", ["nothing-here.md", "search-notes", "../../README.md", "README.md", ".md", ""]
)
def test_find_returns_none_for_anything_but_a_requirements_file(
    settings: Settings, repo: Repository, file_name: str
) -> None:
    hand_made(repo, "search-notes.md")
    assert requirements.find(settings, repo, file_name) is None
