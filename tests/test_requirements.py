"""Requirements: Markdown files in the primary checkout, named by their files, single-file
commits."""

import contextlib
import sqlite3
import subprocess
import threading
from pathlib import Path

import pytest

from repocop import db
from repocop.config import Settings
from repocop.services import repositories, requirements
from repocop.services.repositories import Repository
from repocop.services.requirements import Kind, Location, RequirementError
from tests.conftest import run_git

TODO = Path("specs/changes/todo")


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo)).repository


def create(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    name: str = "Bulk user import",
    body: str = "Import users from CSV.",
    kind: str = "feature",
) -> requirements.Saved:
    return requirements.create(conn, settings, repo, name=name, body=body, kind=kind)


def head_files(checkout: Path) -> list[str]:
    return run_git("show", "--name-only", "--format=", "HEAD", cwd=checkout).splitlines()


# ---------------------------------------------------------------- slugs


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Bulk user import", "bulk-user-import"),
        ("  Fix: login crash (iOS 17)!  ", "fix-login-crash-ios-17"),
        ("Ünïcode naïve café", "n-code-na-ve-caf"),
        ("x" * 80, "x" * 50),
        ("a " * 40, ("a-" * 25).rstrip("-")),
    ],
)
def test_slugify_keeps_lowercase_letters_digits_and_single_dashes(name: str, slug: str) -> None:
    assert requirements.slugify(name) == slug


# ---------------------------------------------------------------- create


def test_create_writes_the_text_alone_named_by_the_name(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    saved = create(conn, settings, repo)
    assert saved.requirement.path == "specs/changes/todo/bulk-user-import.md"
    assert saved.requirement.name == "bulk-user-import"
    text = (repo.primary_path / saved.requirement.path).read_text()
    assert text == "Import users from CSV.\n"  # no title heading: the file name names it


def test_create_commits_that_file_alone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    (repo.primary_path / "staged.txt").write_text("the human's\n")
    run_git("add", "staged.txt", cwd=repo.primary_path)
    saved = create(conn, settings, repo)
    assert saved.committed
    assert head_files(repo.primary_path) == [saved.requirement.path]
    assert run_git("log", "-1", "--format=%s", cwd=repo.primary_path) == "Add bulk-user-import"
    assert run_git("diff", "--cached", "--name-only", cwd=repo.primary_path) == "staged.txt"


def test_create_records_only_references_in_the_database(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    saved = create(conn, settings, repo, kind="fix")
    row = dict(conn.execute("SELECT id, repository_id, path, kind FROM requirements").fetchone())
    assert row == {
        "id": saved.requirement.id,
        "repository_id": repo.id,
        "path": "specs/changes/todo/bulk-user-import.md",
        "kind": "fix",
    }


def test_create_writes_into_the_todo_folder_of_the_repositorys_changes_folder(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    custom = settings.model_copy(update={"changes_dir": "docs/rfcs"})
    repo = repositories.register(conn, custom, str(remote_repo)).repository
    saved = create(conn, custom, repo, name="Faster search")
    assert saved.requirement.path == "docs/rfcs/todo/faster-search.md"
    assert (repo.primary_path / "docs/rfcs/todo/faster-search.md").is_file()


@pytest.mark.parametrize(
    "existing",
    [
        "specs/changes/todo/bulk-user-import.md",
        "specs/changes/archive/bulk-user-import.md",
        "specs/changes/archive/2026-10-14T150616Z-bulk-user-import.md",
    ],
)
def test_create_refuses_a_name_already_in_the_folder_or_the_archive(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, existing: str
) -> None:
    (repo.primary_path / existing).parent.mkdir(parents=True, exist_ok=True)
    (repo.primary_path / existing).write_text("The first one.\n")
    head = run_git("rev-parse", "HEAD", cwd=repo.primary_path)
    with pytest.raises(RequirementError, match="bulk-user-import is already"):
        create(conn, settings, repo)
    assert (repo.primary_path / existing).read_text() == "The first one.\n"
    assert run_git("rev-parse", "HEAD", cwd=repo.primary_path) == head
    assert requirements.list_for(conn, repo) == []


def test_create_refuses_a_name_repocop_has_recorded(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    first = create(conn, settings, repo).requirement
    run_git("rm", "-q", first.path, cwd=repo.primary_path)
    run_git("commit", "-qm", "Drop it", cwd=repo.primary_path)
    with pytest.raises(RequirementError, match="bulk-user-import is already"):
        create(conn, settings, repo)
    assert not (repo.primary_path / first.path).exists()
    assert requirements.list_for(conn, repo) == [first]


def test_create_normalizes_browser_line_endings(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    saved = create(conn, settings, repo, body="line one\r\nline two\r\n")
    text = (repo.primary_path / saved.requirement.path).read_bytes()
    assert text == b"line one\nline two\n"


@pytest.mark.parametrize(
    ("name", "kind", "message"),
    [
        ("", "feature", "name"),
        ("   ", "feature", "name"),
        ("two\nlines", "feature", "single line"),
        ("!!!", "feature", "letters or digits"),
        ("Fine name", "chore", "kind"),
    ],
)
def test_create_rejects_invalid_input_without_writing(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    name: str,
    kind: str,
    message: str,
) -> None:
    with pytest.raises(RequirementError, match=message):
        create(conn, settings, repo, name=name, kind=kind)
    assert not (repo.primary_path / "specs").exists()
    assert requirements.list_for(conn, repo) == []


def test_create_refuses_a_checkout_in_the_middle_of_a_merge(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    checkout = repo.primary_path
    run_git("checkout", "-q", "-b", "other", cwd=checkout)
    (checkout / "README.md").write_text("other\n")
    run_git("commit", "-qam", "other", cwd=checkout)
    run_git("checkout", "-q", "main", cwd=checkout)
    (checkout / "README.md").write_text("main\n")
    run_git("commit", "-qam", "main", cwd=checkout)
    with contextlib.suppress(subprocess.CalledProcessError):
        run_git("merge", "other", cwd=checkout)
    with pytest.raises(RequirementError, match="middle of a merge"):
        create(conn, settings, repo)
    assert not (checkout / "specs").exists()


def test_create_refuses_a_detached_head(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    run_git("checkout", "-q", "--detach", cwd=repo.primary_path)
    with pytest.raises(RequirementError, match="detached HEAD"):
        create(conn, settings, repo)
    assert not (repo.primary_path / "specs").exists()


def test_create_refuses_a_requirements_folder_outside_the_checkout(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo.primary_path / "specs").symlink_to(outside)
    with pytest.raises(RequirementError, match="outside"):
        create(conn, settings, repo)
    assert list(outside.iterdir()) == []


def test_create_keeps_the_requirement_when_the_commit_fails(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    hook = repo.primary_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'rejected by hook' >&2\nexit 1\n")
    hook.chmod(0o755)
    saved = create(conn, settings, repo)
    assert not saved.committed
    assert (repo.primary_path / saved.requirement.path).is_file()
    assert requirements.is_uncommitted(settings, repo, saved.requirement)


def test_concurrent_creates_both_commit_their_own_file(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    results: list[requirements.Saved] = []

    def add(name: str) -> None:
        own = db.connect(settings.database_path)
        try:
            results.append(create(own, settings, repo, name=name))
        finally:
            own.close()

    threads = [threading.Thread(target=add, args=(name,)) for name in ("First", "Second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(saved.requirement.name for saved in results) == ["first", "second"]
    assert all(saved.committed for saved in results)


# ---------------------------------------------------------------- read and update


def test_read_returns_the_text_and_a_version(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    content = requirements.read(settings, repo, requirement)
    assert content.body == "Import users from CSV."
    assert content.version


def test_read_keeps_an_older_changes_heading_as_part_of_its_text(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    (repo.primary_path / requirement.path).write_text("# Old title\n\nJust notes.\n")
    content = requirements.read(settings, repo, requirement)
    assert content.body == "# Old title\n\nJust notes."


def test_update_rewrites_the_file_and_commits_it(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    version = requirements.read(settings, repo, requirement).version
    saved = requirements.update(
        conn,
        settings,
        repo,
        requirement,
        body="New body.",
        kind="fix",
        version=version,
    )
    assert saved.committed
    assert saved.requirement.kind is Kind.FIX
    assert saved.requirement.path == requirement.path  # the slug is fixed at creation
    assert (repo.primary_path / requirement.path).read_text() == "New body.\n"
    message = run_git("log", "-1", "--format=%s", cwd=repo.primary_path)
    assert message == "Update bulk-user-import"


def test_update_refuses_when_the_file_changed_since_it_was_read(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    version = requirements.read(settings, repo, requirement).version
    (repo.primary_path / requirement.path).write_text("# Edited elsewhere\n")
    with pytest.raises(RequirementError, match="changed on disk"):
        requirements.update(
            conn, settings, repo, requirement, body="Mine", kind="feature", version=version
        )
    assert (repo.primary_path / requirement.path).read_text() == "# Edited elsewhere\n"


def test_update_without_changes_makes_no_commit(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    content = requirements.read(settings, repo, requirement)
    head = run_git("rev-parse", "HEAD", cwd=repo.primary_path)
    requirements.update(
        conn,
        settings,
        repo,
        requirement,
        body=content.body,
        kind="feature",
        version=content.version,
    )
    assert run_git("rev-parse", "HEAD", cwd=repo.primary_path) == head


def test_update_of_the_kind_alone_leaves_the_file_untouched(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    content = requirements.read(settings, repo, requirement)
    saved = requirements.update(
        conn,
        settings,
        repo,
        requirement,
        body=content.body,
        kind="fix",
        version=content.version,
    )
    assert requirements.list_for(conn, repo) == [saved.requirement]
    assert saved.requirement.kind is Kind.FIX
    assert requirements.read(settings, repo, requirement).version == content.version


# ---------------------------------------------------------------- commit, location, list


def test_commit_commits_a_hand_edited_requirement(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    (repo.primary_path / requirement.path).write_text("# Bulk user import\n\nEdited by hand.\n")
    assert requirements.is_uncommitted(settings, repo, requirement)
    requirements.commit(settings, repo, requirement)
    assert not requirements.is_uncommitted(settings, repo, requirement)
    assert head_files(repo.primary_path) == [requirement.path]


def test_commit_refuses_when_there_is_nothing_to_commit(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    with pytest.raises(RequirementError, match="nothing to commit"):
        requirements.commit(settings, repo, requirement)


def test_location_is_active_at_its_path(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    assert requirements.location(settings, repo, requirement) is Location.ACTIVE


def test_location_is_archived_once_moved_to_the_archive_folder(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    archive = repo.primary_path / "specs/changes/archive"
    archive.mkdir()
    run_git("mv", requirement.path, "specs/changes/archive/", cwd=repo.primary_path)
    assert requirements.location(settings, repo, requirement) is Location.ARCHIVED
    assert requirements.read(settings, repo, requirement).body == "Import users from CSV."


def test_location_is_archived_under_a_name_stamped_with_when(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    (repo.primary_path / "specs/changes/archive").mkdir()
    stamped = "specs/changes/archive/2026-10-14T150616Z-bulk-user-import.md"
    run_git("mv", requirement.path, stamped, cwd=repo.primary_path)
    assert requirements.location(settings, repo, requirement) is Location.ARCHIVED
    assert requirements.read(settings, repo, requirement).body == "Import users from CSV."
    assert requirements.archived_path(repo.primary_path, requirement.path) == stamped


def test_archived_path_takes_the_latest_stamp_and_ignores_other_names(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
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
    requirement = create(conn, settings, repo).requirement
    (repo.primary_path / requirement.path).unlink()
    assert requirements.location(settings, repo, requirement) is Location.MISSING


def test_update_refuses_an_archived_requirement(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = create(conn, settings, repo).requirement
    version = requirements.read(settings, repo, requirement).version
    (repo.primary_path / "specs/changes/archive").mkdir()
    run_git("mv", requirement.path, "specs/changes/archive/", cwd=repo.primary_path)
    with pytest.raises(RequirementError, match="isn't at"):
        requirements.update(
            conn, settings, repo, requirement, body="X", kind="feature", version=version
        )


def test_list_for_returns_a_repositorys_recorded_requirements(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    create(conn, settings, repo, name="First")
    create(conn, settings, repo, name="Second")
    assert [r.name for r in requirements.list_for(conn, repo)] == ["first", "second"]


def test_get_returns_none_for_an_unknown_key(conn: sqlite3.Connection) -> None:
    assert requirements.get(conn, 999) is None


# ---------------------------------------------------------------- hand-made files


def hand_made(
    repo: Repository,
    name: str,
    text: str = "# Search notes\n\nFaster search.\n",
    commit: bool = True,
) -> str:
    """Write a file into the requirements folder by hand; return its relative path."""
    (repo.primary_path / TODO).mkdir(parents=True, exist_ok=True)
    (repo.primary_path / TODO / name).write_text(text)
    if commit:
        run_git("add", ".", cwd=repo.primary_path)
        run_git("commit", "-qm", f"Add {name}", cwd=repo.primary_path)
    return str(TODO / name)


def test_in_folder_lists_every_markdown_file_as_a_requirement_recorded_or_not(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    recorded = create(conn, settings, repo).requirement
    hand_made(repo, "search-notes.md")
    hand_made(repo, "req-7-hand-made.md")
    hand_made(repo, "diagram.png")
    assert requirements.in_folder(conn, settings, repo) == [
        recorded,
        requirements.Requirement(repo.id, str(TODO / "req-7-hand-made.md")),
        requirements.Requirement(repo.id, str(TODO / "search-notes.md")),
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


def test_find_returns_a_hand_made_file_not_recorded_yet(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    path = hand_made(repo, "search-notes.md")
    found = requirements.find(conn, settings, repo, "search-notes.md")
    assert found == requirements.Requirement(repo.id, path, Kind.FEATURE, None)
    assert found is not None and found.name == "search-notes"
    assert requirements.list_for(conn, repo) == []


def test_find_returns_a_recorded_requirement_with_its_key_and_kind(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    saved = create(conn, settings, repo, kind="fix").requirement
    assert requirements.find(conn, settings, repo, "bulk-user-import.md") == saved


def test_find_returns_a_requirement_recorded_under_an_id_by_its_file_name(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    path = hand_made(repo, "req-7-hand-made.md")
    conn.execute(
        "INSERT INTO requirements (id, repository_id, path, kind, created_at, updated_at)"
        " VALUES (7, ?, ?, 'fix', '', '')",
        (repo.id, path),
    )
    found = requirements.find(conn, settings, repo, "req-7-hand-made.md")
    assert found == requirements.Requirement(repo.id, path, Kind.FIX, 7)


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


def test_update_records_a_hand_made_file_whose_kind_changes(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    hand_made(repo, "search-notes.md")
    found = requirements.find(conn, settings, repo, "search-notes.md")
    assert found is not None
    version = requirements.read(settings, repo, found).version
    body = requirements.read(settings, repo, found).body
    saved = requirements.update(conn, settings, repo, found, body=body, kind="fix", version=version)
    assert saved.requirement.id is not None
    assert requirements.list_for(conn, repo) == [saved.requirement]
    assert saved.requirement.kind is Kind.FIX
