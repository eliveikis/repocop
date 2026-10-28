"""Worktrees: RepoCop-owned, one per requirement, never inside a human-owned checkout."""

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import git, repositories, worktrees
from repocop.services.repositories import Repository
from repocop.services.worktrees import WorktreeError
from tests.conftest import run_git


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo), default_branch="main").repository


@pytest.mark.parametrize("name", ["login-crash", "req-124-login-crash"])
def test_requirement_names_are_its_name_on_a_branch_an_agent_made(name: str) -> None:
    assert worktrees.requirement_names(name) == (name, f"agent/{name}")


def test_create_adds_a_worktree_on_a_new_branch_from_primary_head(
    settings: Settings, repo: Repository
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    assert worktree.path == settings.worktrees_root / "sample" / "req-1-x"
    assert worktree.branch == "feature/req-1-x"
    assert worktree.base_commit == git.head_commit(repo.primary_path)
    assert git.current_branch(worktree.path) == "feature/req-1-x"
    assert (worktree.path / "README.md").is_file()


def test_create_leaves_the_primary_checkout_untouched(settings: Settings, repo: Repository) -> None:
    head = git.head_commit(repo.primary_path)
    worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    assert git.current_branch(repo.primary_path) == "main"
    assert git.head_commit(repo.primary_path) == head
    assert run_git("status", "--porcelain", cwd=repo.primary_path) == ""


def test_create_refuses_a_branch_that_already_exists(settings: Settings, repo: Repository) -> None:
    run_git("branch", "feature/req-1-x", cwd=repo.primary_path)
    with pytest.raises(WorktreeError, match="already exists"):
        worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    assert not (settings.worktrees_root / "sample" / "req-1-x").exists()


def test_create_refuses_a_folder_that_already_exists(settings: Settings, repo: Repository) -> None:
    folder = settings.worktrees_root / "sample" / "req-1-x"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("mine\n")
    with pytest.raises(WorktreeError, match="already exists"):
        worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    assert [p.name for p in folder.iterdir()] == ["notes.txt"]
    assert not git.branch_exists(repo.primary_path, "feature/req-1-x")


def test_create_refuses_a_worktree_root_inside_the_primary_checkout(
    settings: Settings, repo: Repository
) -> None:
    tampered = dataclasses.replace(repo, worktrees_root=repo.primary_path / "worktrees")
    with pytest.raises(WorktreeError, match="RepoCop-owned"):
        worktrees.create(tampered, settings, "req-1-x", "feature/req-1-x")
    assert not (repo.primary_path / "worktrees").exists()
    assert not git.branch_exists(repo.primary_path, "feature/req-1-x")


def test_create_refuses_a_worktree_root_other_than_the_configured_one(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    tampered = dataclasses.replace(repo, worktrees_root=tmp_path / "elsewhere")
    with pytest.raises(WorktreeError, match="RepoCop-owned"):
        worktrees.create(tampered, settings, "req-1-x", "feature/req-1-x")


def test_create_refuses_a_worktree_folder_that_leaves_its_root(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (settings.worktrees_root / "sample").symlink_to(outside)
    with pytest.raises(WorktreeError, match="RepoCop-owned"):
        worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    assert list(outside.iterdir()) == []


def test_worktrees_keep_their_changes_apart(settings: Settings, repo: Repository) -> None:
    first = worktrees.create(repo, settings, "req-1-a", "feature/req-1-a")
    second = worktrees.create(repo, settings, "req-2-b", "feature/req-2-b")
    (first.path / "README.md").write_text("changed in req-1\n")
    (first.path / "new.txt").write_text("only in req-1\n")
    assert (second.path / "README.md").read_text() == "# sample\n"
    assert not (second.path / "new.txt").exists()
    assert run_git("status", "--porcelain", cwd=second.path) == ""
    assert run_git("status", "--porcelain", cwd=repo.primary_path) == ""


def test_is_worktree_recognises_a_created_worktree(settings: Settings, repo: Repository) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    assert worktrees.is_worktree(repo, settings, worktree.path)
    assert not worktrees.is_worktree(repo, settings, settings.worktrees_root / "sample" / "nope")


def test_is_worktree_rejects_a_checkout_outside_repocop_folder(
    settings: Settings, repo: Repository
) -> None:
    assert not worktrees.is_worktree(repo, settings, repo.primary_path)


def test_is_worktree_rejects_another_repositorys_checkout_at_the_worktree_path(
    settings: Settings, repo: Repository, remote_repo: Path, tmp_path: Path
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    worktree.path.rename(tmp_path / "moved-away")
    other = remote_repo.parent / "other.git"
    run_git("clone", "-q", "--bare", str(remote_repo), str(other), cwd=tmp_path)
    run_git("clone", "-q", str(other), str(worktree.path), cwd=tmp_path)
    assert not worktrees.is_worktree(repo, settings, worktree.path)


def test_is_worktree_rejects_a_symlink_at_the_worktree_path(
    settings: Settings, repo: Repository
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    real = worktree.path.parent / "req-1-real"
    worktree.path.rename(real)
    worktree.path.symlink_to(real)
    assert not worktrees.is_worktree(repo, settings, worktree.path)


def test_snapshot_reports_commits_since_the_base_and_uncommitted_files(
    settings: Settings, repo: Repository
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    (worktree.path / "done.txt").write_text("committed\n")
    run_git("add", "done.txt", cwd=worktree.path)
    run_git("commit", "-qm", "Done part", cwd=worktree.path)
    (worktree.path / "half.txt").write_text("half done\n")
    snapshot = worktrees.snapshot(repo, settings, worktree.path, worktree.base_commit)
    assert snapshot == worktrees.Snapshot(commits=1, uncommitted=("half.txt",))


def test_snapshot_is_none_when_the_worktree_is_gone(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    worktree.path.rename(tmp_path / "moved-away")
    assert worktrees.snapshot(repo, settings, worktree.path, worktree.base_commit) is None


def test_is_worktree_rejects_a_worktree_of_a_repository_that_replaced_the_primary(
    settings: Settings, repo: Repository, remote_repo: Path, tmp_path: Path
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    other = tmp_path / "other.git"
    run_git("clone", "-q", "--bare", str(remote_repo), str(other), cwd=tmp_path)
    repo.primary_path.rename(tmp_path / "primary-moved-away")
    worktree.path.rename(tmp_path / "worktree-moved-away")
    run_git("clone", "-q", str(other), str(repo.primary_path), cwd=tmp_path)
    run_git("worktree", "add", "-q", "-b", "impostor", str(worktree.path), cwd=repo.primary_path)
    assert not worktrees.is_worktree(repo, settings, worktree.path)


def test_changes_shows_git_status_and_the_diff_since_the_base(
    settings: Settings, repo: Repository
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    (worktree.path / "notes.txt").write_text("a new note\n")
    changes = worktrees.changes(repo, settings, worktree.path, worktree.base_commit)
    assert changes is not None
    assert "?? notes.txt" in changes.status.splitlines()
    assert "+a new note" in changes.diff
    assert not changes.clipped


def test_changes_clips_a_very_long_diff(
    settings: Settings, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worktrees, "MAX_DIFF_TEXT", 100)
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    (worktree.path / "big.txt").write_text("line\n" * 200)
    changes = worktrees.changes(repo, settings, worktree.path, worktree.base_commit)
    assert changes is not None and changes.clipped and len(changes.diff) == 100


def test_changes_is_none_when_the_worktree_is_gone(
    settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    worktree = worktrees.create(repo, settings, "req-1-x", "feature/req-1-x")
    worktree.path.rename(tmp_path / "moved-away")
    assert worktrees.changes(repo, settings, worktree.path, worktree.base_commit) is None


def test_task_names_say_an_agent_made_the_branch() -> None:
    assert worktrees.task_names("template-sync", 43) == (
        "template-sync-43",
        "agent/template-sync-43",
    )


def test_create_can_start_from_a_given_branch(settings: Settings, repo: Repository) -> None:
    main = git.head_commit(repo.primary_path)
    run_git("checkout", "-q", "-b", "wip", cwd=repo.primary_path)
    (repo.primary_path / "wip.txt").write_text("wip\n")
    run_git("add", "wip.txt", cwd=repo.primary_path)
    run_git("commit", "-qm", "wip", cwd=repo.primary_path)
    worktree = worktrees.create(
        repo, settings, "template-sync-1", "chore/template-sync-1", start="main"
    )
    assert worktree.base_commit == main
    assert not (worktree.path / "wip.txt").exists()


# ---------------------------------------------------------------- remove


def test_remove_deletes_the_worktree_and_its_branch(settings: Settings, repo: Repository) -> None:
    created = worktrees.create(repo, settings, "sync-1", "agent/sync-1")
    worktrees.remove(repo, settings, created.path, created.branch)
    assert not created.path.exists()
    assert not git.branch_exists(repo.primary_path, "agent/sync-1")


def test_remove_refuses_a_worktree_with_uncommitted_changes(
    settings: Settings, repo: Repository
) -> None:
    created = worktrees.create(repo, settings, "sync-1", "agent/sync-1")
    (created.path / "draft.txt").write_text("not committed\n")
    with pytest.raises(WorktreeError, match="uncommitted"):
        worktrees.remove(repo, settings, created.path, created.branch)
    assert (created.path / "draft.txt").exists()
    assert git.branch_exists(repo.primary_path, "agent/sync-1")


def test_remove_refuses_a_worktree_on_another_branch(settings: Settings, repo: Repository) -> None:
    created = worktrees.create(repo, settings, "sync-1", "agent/sync-1")
    run_git("switch", "-qc", "elsewhere", cwd=created.path)
    with pytest.raises(WorktreeError, match="is on elsewhere, not agent/sync-1"):
        worktrees.remove(repo, settings, created.path, created.branch)
    assert created.path.exists() and git.branch_exists(repo.primary_path, "agent/sync-1")


def test_remove_refuses_a_path_that_is_not_one_of_the_repositorys_worktrees(
    settings: Settings, repo: Repository
) -> None:
    with pytest.raises(WorktreeError, match="isn't a RepoCop worktree"):
        worktrees.remove(repo, settings, repo.primary_path, "main")
    assert repo.primary_path.is_dir() and git.branch_exists(repo.primary_path, "main")
