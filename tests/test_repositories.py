"""Repository registry: register by remote URL (clone or find the checkout), dedupe, status."""

import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import git, repositories
from repocop.services.git import GitError
from repocop.services.repositories import Outcome, RepositoryError, Status
from tests.conftest import HostLayout, push_commit, run_git, write_template


def repository_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT count(*) FROM repositories").fetchone()[0])


def bare_copy(remote_repo: Path, name: str) -> Path:
    """Another bare remote with a different path (so a different identity)."""
    copy = remote_repo.parent / name
    shutil.copytree(remote_repo, copy)
    return copy


# ---------------------------------------------------------------- register


def test_register_clones_a_repository_that_is_not_on_disk(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    registration = repositories.register(conn, settings, str(remote_repo), default_branch="main")
    assert registration.outcome is Outcome.CLONED
    assert (settings.repos_root / "sample" / "README.md").is_file()


def test_register_records_name_remote_and_both_paths(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    assert repositories.get(conn, repo.id) == repo
    assert repo.name == "sample"
    assert repo.remote_url == str(remote_repo)
    assert repo.primary_path == settings.repos_root / "sample"
    assert repo.worktrees_root == settings.worktrees_root / "sample"
    assert repo.default_branch == "main"
    assert repo.changes_dir == settings.changes_dir
    assert repo.created_at == repo.updated_at


def test_register_finds_an_existing_checkout_of_the_same_remote(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, primary_checkout: Path
) -> None:
    (primary_checkout / "notes.txt").write_text("mine\n")
    registration = repositories.register(conn, settings, str(remote_repo), default_branch="main")
    assert registration.outcome is Outcome.FOUND_ON_DISK
    assert registration.repository.primary_path == primary_checkout
    assert (primary_checkout / "notes.txt").read_text() == "mine\n"


def test_register_twice_returns_the_existing_repository(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    first = repositories.register(
        conn, settings, str(remote_repo), default_branch="main"
    ).repository
    again = repositories.register(conn, settings, str(remote_repo), default_branch="main")
    assert again.outcome is Outcome.ALREADY_REGISTERED
    assert again.repository == first
    assert repository_count(conn) == 1


def test_register_matches_another_spelling_of_a_registered_remote(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repositories.register(conn, settings, str(remote_repo), default_branch="main")
    again = repositories.register(
        conn, settings, f"file://{remote_repo}", name="other", default_branch="main"
    )
    assert again.outcome is Outcome.ALREADY_REGISTERED
    assert repository_count(conn) == 1


def test_register_derives_the_name_from_the_url(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    remote = bare_copy(remote_repo, "My.Repo.git")
    assert (
        repositories.register(conn, settings, f"{remote}/", default_branch="main").repository.name
        == "My.Repo"
    )


def test_register_uses_a_given_name(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(
        conn, settings, str(remote_repo), name=" crm-api ", default_branch="main"
    ).repository
    assert repo.name == "crm-api"
    assert repo.primary_path == settings.repos_root / "crm-api"


def test_register_refuses_a_directory_that_is_not_a_checkout_of_the_remote(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    existing = settings.repos_root / "sample"
    existing.mkdir()
    (existing / "notes.txt").write_text("mine\n")
    with pytest.raises(RepositoryError, match="left untouched"):
        repositories.register(conn, settings, str(remote_repo), default_branch="main")
    assert [p.name for p in existing.iterdir()] == ["notes.txt"]
    assert repository_count(conn) == 0


def test_register_refuses_a_checkout_of_a_different_remote(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, primary_checkout: Path
) -> None:
    other = bare_copy(remote_repo, "other.git")
    with pytest.raises(RepositoryError, match="not a checkout of"):
        repositories.register(conn, settings, str(other), name="sample", default_branch="main")
    assert repository_count(conn) == 0


def test_register_refuses_a_name_used_by_another_remote(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repositories.register(conn, settings, str(remote_repo), default_branch="main")
    other = bare_copy(remote_repo, "other.git")
    with pytest.raises(RepositoryError, match="already used"):
        repositories.register(conn, settings, str(other), name="sample", default_branch="main")
    assert repository_count(conn) == 1


@pytest.mark.parametrize("name", ["../evil", "a/b", ".hidden", "-x", "has space", "x" * 101])
def test_register_rejects_unsafe_names(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, host: HostLayout, name: str
) -> None:
    with pytest.raises(RepositoryError, match="name"):
        repositories.register(conn, settings, str(remote_repo), name=name, default_branch="main")
    assert list(host.repos_root.iterdir()) == []
    assert repository_count(conn) == 0


def test_register_refuses_a_symlink_that_leaves_repos_root(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    run_git("clone", "-q", str(remote_repo), str(elsewhere), cwd=tmp_path)
    (settings.repos_root / "sample").symlink_to(elsewhere)
    with pytest.raises(RepositoryError, match="outside"):
        repositories.register(conn, settings, str(remote_repo), default_branch="main")
    assert repository_count(conn) == 0


def test_register_rejects_an_unsupported_url_without_touching_disk(
    conn: sqlite3.Connection, settings: Settings, host: HostLayout
) -> None:
    with pytest.raises(GitError, match="remote URL"):
        repositories.register(conn, settings, "ext::sh -c touch% pwned", default_branch="main")
    assert list(host.repos_root.iterdir()) == []


def test_register_registers_nothing_when_the_clone_fails(
    conn: sqlite3.Connection, settings: Settings, host: HostLayout
) -> None:
    with pytest.raises(RepoCopError, match="clone failed"):
        repositories.register(conn, settings, "file:///no/such/repo.git", default_branch="main")
    assert list(host.repos_root.iterdir()) == []
    assert repository_count(conn) == 0


def test_register_concurrent_adds_of_one_remote_register_it_once(
    conn: sqlite3.Connection,
    settings: Settings,
    remote_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_clone = git.clone

    def slow_clone(url: str, dest: Path, *, timeout: float = git.NETWORK_TIMEOUT_S) -> None:
        time.sleep(0.3)  # widen the window in which both adds could pass the duplicate check
        real_clone(url, dest, timeout=timeout)

    monkeypatch.setattr(git, "clone", slow_clone)
    outcomes: list[Outcome] = []

    def add(name: str) -> None:
        own = db.connect(settings.database_path)
        try:
            outcomes.append(
                repositories.register(
                    own, settings, str(remote_repo), name, default_branch="main"
                ).outcome
            )
        finally:
            own.close()

    threads = [threading.Thread(target=add, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [Outcome.ALREADY_REGISTERED, Outcome.CLONED]
    assert repository_count(conn) == 1


# ---------------------------------------------------------------- register a checkout by name


def test_register_by_name_takes_the_remote_from_the_checkouts_origin(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, primary_checkout: Path
) -> None:
    registration = repositories.register(conn, settings, "", "sample", default_branch="main")
    assert registration.outcome is Outcome.FOUND_ON_DISK
    assert registration.repository.primary_path == primary_checkout
    assert registration.repository.remote_url == str(remote_repo)


def test_register_by_name_of_a_registered_remote_returns_it(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, primary_checkout: Path
) -> None:
    first = repositories.register(
        conn, settings, str(remote_repo), default_branch="main"
    ).repository
    again = repositories.register(conn, settings, "", "sample", default_branch="main")
    assert (again.repository, again.outcome) == (first, Outcome.ALREADY_REGISTERED)


def test_register_needs_a_url_or_a_name(conn: sqlite3.Connection, settings: Settings) -> None:
    with pytest.raises(RepositoryError, match="remote URL"):
        repositories.register(conn, settings, "", " ", default_branch="main")


def test_register_by_name_refuses_a_folder_that_is_not_there(
    conn: sqlite3.Connection, settings: Settings, host: HostLayout
) -> None:
    with pytest.raises(RepositoryError, match="remote URL to clone it"):
        repositories.register(conn, settings, "", "sample", default_branch="main")
    assert list(host.repos_root.iterdir()) == []


def test_register_by_name_refuses_a_folder_that_is_not_a_checkout(
    conn: sqlite3.Connection, settings: Settings, host: HostLayout
) -> None:
    (host.repos_root / "sample").mkdir()
    with pytest.raises(RepositoryError, match="isn't a git checkout"):
        repositories.register(conn, settings, "", "sample", default_branch="main")
    assert repository_count(conn) == 0


def test_register_by_name_refuses_a_checkout_without_an_origin(
    conn: sqlite3.Connection, settings: Settings, primary_checkout: Path
) -> None:
    run_git("remote", "remove", "origin", cwd=primary_checkout)
    with pytest.raises(RepositoryError, match="no origin remote"):
        repositories.register(conn, settings, "", "sample", default_branch="main")
    assert repository_count(conn) == 0


def test_register_by_name_refuses_an_unsupported_origin(
    conn: sqlite3.Connection, settings: Settings, primary_checkout: Path
) -> None:
    run_git("remote", "set-url", "origin", "ext::sh -c touch% pwned", cwd=primary_checkout)
    with pytest.raises(GitError, match="unsupported remote URL"):
        repositories.register(conn, settings, "", "sample", default_branch="main")
    assert repository_count(conn) == 0


def test_register_by_name_refuses_a_symlinked_folder(
    conn: sqlite3.Connection, settings: Settings, primary_checkout: Path
) -> None:
    (settings.repos_root / "alias").symlink_to(primary_checkout)
    with pytest.raises(RepositoryError, match="symlink"):
        repositories.register(conn, settings, "", "alias", default_branch="main")
    assert repository_count(conn) == 0


def test_register_by_name_rejects_unsafe_names_without_touching_disk(
    conn: sqlite3.Connection, settings: Settings, host: HostLayout
) -> None:
    with pytest.raises(RepositoryError, match="invalid repository name"):
        repositories.register(conn, settings, "", "../outside", default_branch="main")


# ---------------------------------------------------------------- list and status


def test_list_all_orders_repositories_by_name(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repositories.register(
        conn, settings, str(bare_copy(remote_repo, "zeta.git")), default_branch="main"
    )
    repositories.register(
        conn, settings, str(bare_copy(remote_repo, "alpha.git")), default_branch="main"
    )
    assert [repo.name for repo in repositories.list_all(conn)] == ["alpha", "zeta"]


def test_get_returns_none_for_an_unknown_id(conn: sqlite3.Connection) -> None:
    assert repositories.get(conn, 999) is None


def commit_everything(checkout: Path, message: str = "commit") -> None:
    """Commit everything on main, and push it to origin as merged work is."""
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-qm", message, cwd=checkout)
    run_git("push", "-q", "origin", "main", cwd=checkout)


def test_status_is_ready_once_the_default_branch_has_the_template(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    write_template(settings.template_dir, repo.primary_path)
    commit_everything(repo.primary_path)
    assert repositories.status(repo, settings) is Status.READY


def test_status_is_behind_while_the_default_branch_lacks_template_files(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    assert repositories.status(repo, settings) is Status.BEHIND


def test_status_is_behind_while_a_template_file_differs_on_the_default_branch(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    write_template(settings.template_dir, repo.primary_path)
    (repo.primary_path / "CLAUDE.md").write_text("# Mine\n")
    commit_everything(repo.primary_path)
    assert repositories.status(repo, settings) is Status.BEHIND


def test_status_is_not_hidden_by_template_files_left_uncommitted(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    write_template(settings.template_dir, repo.primary_path)
    assert repositories.status(repo, settings) is Status.BEHIND


def test_status_is_not_changed_by_uncommitted_edits(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    write_template(settings.template_dir, repo.primary_path)
    commit_everything(repo.primary_path)
    (repo.primary_path / "CLAUDE.md").write_text("# edited, not committed\n")
    (repo.primary_path / "logo.bin").unlink()
    assert repositories.status(repo, settings) is Status.READY


def test_status_is_behind_when_the_template_cannot_be_compared(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    (repo.primary_path / "CLAUDE.md").mkdir()
    (repo.primary_path / "CLAUDE.md" / "notes.md").write_text("notes\n")
    commit_everything(repo.primary_path)
    assert repositories.status(repo, settings) is Status.BEHIND


def test_status_says_a_repository_with_no_commits_needs_one(
    conn: sqlite3.Connection, settings: Settings, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.git"
    run_git("init", "-q", "--bare", str(empty), cwd=tmp_path)
    repo = repositories.register(conn, settings, str(empty), default_branch="main").repository
    assert repositories.status(repo, settings) is Status.NO_COMMITS


def test_checkout_state_reads_the_primary_checkout(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    state = repositories.checkout_state(repo, settings)
    assert (state.branch, state.upstream) == ("main", "origin/main")


def test_checkout_state_refuses_a_path_that_no_longer_holds_the_checkout(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    outside = tmp_path / "outside"
    repo.primary_path.rename(outside)
    repo.primary_path.symlink_to(outside)
    with pytest.raises(RepositoryError, match="isn't there"):
        repositories.checkout_state(repo, settings)


def test_fetch_updates_the_primary_checkouts_remote_tracking_branch(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    pushed = push_commit(remote_repo, tmp_path)
    repositories.fetch(repo, settings)
    assert run_git("rev-parse", "origin/main", cwd=repo.primary_path) == pushed


def test_fetch_never_runs_in_a_path_that_no_longer_holds_the_checkout(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    outside = tmp_path / "outside"
    repo.primary_path.rename(outside)
    repo.primary_path.symlink_to(outside)
    with pytest.raises(RepositoryError, match="isn't there"):
        repositories.fetch(repo, settings)
    assert not (outside / ".git" / "FETCH_HEAD").exists()


def test_status_is_missing_when_the_checkout_is_gone(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    repo.primary_path.rename(tmp_path / "moved-away")
    assert repositories.status(repo, settings) is Status.MISSING


def test_status_is_missing_when_repos_root_no_longer_contains_the_checkout(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    new_root = tmp_path / "new-code"
    new_root.mkdir()
    moved = settings.model_copy(update={"repos_root": new_root})
    assert repositories.status(repo, moved) is Status.MISSING


def test_status_is_missing_when_the_checkout_is_swapped_for_a_symlink_out_of_repos_root(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    outside = tmp_path / "outside"
    repo.primary_path.rename(outside)
    repo.primary_path.symlink_to(outside)
    assert repositories.status(repo, settings) is Status.MISSING


def test_status_is_missing_when_another_repository_replaces_the_checkout(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path, tmp_path: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    other = bare_copy(remote_repo, "other.git")
    repo.primary_path.rename(tmp_path / "moved-away")
    run_git("clone", "-q", str(other), str(repo.primary_path), cwd=tmp_path)
    assert repositories.status(repo, settings) is Status.MISSING
    with pytest.raises(RepositoryError, match="isn't a checkout of"):
        repositories.require_checkout(repo, settings)


def test_status_is_missing_when_the_checkout_is_a_symlink_inside_repos_root(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    moved = settings.repos_root / "sample-real"
    repo.primary_path.rename(moved)
    repo.primary_path.symlink_to(moved)
    assert repositories.status(repo, settings) is Status.MISSING


def test_register_refuses_a_symlink_as_the_checkout(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    real = settings.repos_root / "sample-real"
    run_git("clone", "-q", str(remote_repo), str(real), cwd=settings.repos_root)
    (settings.repos_root / "sample").symlink_to(real)
    with pytest.raises(RepositoryError, match="symlink"):
        repositories.register(conn, settings, str(remote_repo), default_branch="main")
    assert repository_count(conn) == 0
