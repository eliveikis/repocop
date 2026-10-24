"""Template sync: compare with the default branch, commit picked files on a sync branch."""

import json
import sqlite3
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.services import bootstrap, git, repositories, tasks, template_sync, worktrees
from repocop.services.repositories import Repository
from repocop.services.tasks import Status
from repocop.services.template_sync import TemplateSyncError
from tests.conftest import run_git, write_template


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    return repositories.register(conn, settings, str(remote_repo)).repository


def commit_everything(checkout: Path, message: str = "commit") -> None:
    """Commit everything on the checked-out branch, and push it to origin as merged work is."""
    run_git("add", "-A", cwd=checkout)
    run_git("commit", "-qm", message, cwd=checkout)
    run_git("push", "-q", "origin", "HEAD", cwd=checkout)


def commit_the_template(settings: Settings, repo: Repository) -> None:
    write_template(settings.template_dir, repo.primary_path)
    commit_everything(repo.primary_path, "Add the template")


def committed_files(worktree: Path) -> list[str]:
    return sorted(run_git("show", "--name-only", "--format=", "HEAD", cwd=worktree).split())


RETIRED = ".claude/rules/design.md"


def commit_a_retired_file(repo: Repository) -> None:
    """Commit a file carrying the template's marker, which the template doesn't ship."""
    (repo.primary_path / RETIRED).parent.mkdir(parents=True, exist_ok=True)
    (repo.primary_path / RETIRED).write_text("<!-- managed by template -->\n# Design\n")
    commit_everything(repo.primary_path, "Add a rule the template has since dropped")


# ---------------------------------------------------------------- plan


def test_plan_compares_the_template_with_the_default_branch(
    settings: Settings, repo: Repository
) -> None:
    plan = repositories.template_plan(repo, settings)
    assert plan.ref == "origin/main"
    assert {f.state for f in plan.files} == {bootstrap.FileState.MISSING}


def test_plan_of_a_repository_with_the_template_committed_is_up_to_date(
    settings: Settings, repo: Repository
) -> None:
    commit_the_template(settings, repo)
    assert repositories.template_plan(repo, settings).up_to_date


def test_a_new_repository_is_brought_up_to_the_template_by_a_sync(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    assert repositories.status(repo, settings) is repositories.Status.BEHIND
    missing = [f.path for f in repositories.template_plan(repo, settings).missing]
    task = template_sync.apply(conn, settings, repo, create=missing, overwrite=[])
    assert task is not None and task.status is Status.COMPLETED and task.branch is not None
    main = git.head_commit(repo.primary_path)
    run_git("push", "-q", "origin", task.branch, cwd=repo.primary_path)
    run_git("update-ref", "refs/heads/main", task.branch, cwd=Path(repo.remote_url))  # merged
    assert repositories.status(repo, settings) is repositories.Status.BEHIND  # until fetched
    repositories.fetch(repo, settings)
    assert repositories.status(repo, settings) is repositories.Status.READY
    assert git.head_commit(repo.primary_path) == main  # the checkout's own main is untouched
    assert run_git("status", "--porcelain", cwd=repo.primary_path) == ""


def test_plan_ignores_commits_the_local_default_branch_has_not_pushed(
    settings: Settings, repo: Repository
) -> None:
    write_template(settings.template_dir, repo.primary_path)
    run_git("add", "-A", cwd=repo.primary_path)
    run_git("commit", "-qm", "Not pushed", cwd=repo.primary_path)
    assert not repositories.template_plan(repo, settings).up_to_date
    assert repositories.status(repo, settings) is repositories.Status.BEHIND


def test_plan_says_to_fetch_when_origin_has_no_default_branch_in_the_checkout(
    settings: Settings, repo: Repository
) -> None:
    run_git("update-ref", "-d", "refs/remotes/origin/main", cwd=repo.primary_path)
    with pytest.raises(
        repositories.RepositoryError,
        match=r"origin/main isn't in sample's checkout\. Fetch it first",
    ):
        repositories.template_plan(repo, settings)
    assert repositories.status(repo, settings) is repositories.Status.BEHIND


# ---------------------------------------------------------------- apply


def test_apply_with_nothing_picked_changes_nothing(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    assert template_sync.apply(conn, settings, repo, create=[], overwrite=[]) is None
    assert tasks.list_for_repository(conn, repo) == []
    assert not git.branch_exists(repo.primary_path, "agent/template-sync-1")
    assert not (settings.worktrees_root / "sample").exists()


def test_apply_commits_the_picked_files_on_a_sync_branch(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = template_sync.apply(
        conn, settings, repo, create=["CLAUDE.md", ".claude/skills/demo/run.sh"], overwrite=[]
    )
    assert task is not None
    assert (task.workflow, task.status, task.requirement_id) == (
        "template-sync",
        Status.COMPLETED,
        None,
    )
    assert task.branch == f"agent/template-sync-{task.id}"
    assert task.worktree_path == settings.worktrees_root / "sample" / f"template-sync-{task.id}"
    assert committed_files(task.worktree_path) == [".claude/skills/demo/run.sh", "CLAUDE.md"]
    message = run_git("log", "-1", "--format=%B", cwd=task.worktree_path)
    assert "- create CLAUDE.md" in message and "- create .claude/skills/demo/run.sh" in message
    assert (task.worktree_path / "CLAUDE.md").read_text() == "# sample\n"
    mode = run_git("ls-tree", "HEAD", "--", ".claude/skills/demo/run.sh", cwd=task.worktree_path)
    assert mode.startswith("100755")


def test_apply_leaves_the_primary_checkout_untouched(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    head = git.head_commit(repo.primary_path)
    template_sync.apply(conn, settings, repo, create=["CLAUDE.md"], overwrite=[])
    assert git.head_commit(repo.primary_path) == head
    assert git.current_branch(repo.primary_path) == "main"
    assert git.short_status(repo.primary_path) == "## main...origin/main"
    assert not (repo.primary_path / "CLAUDE.md").exists()


def test_apply_starts_from_origins_default_branch_not_the_checked_out_one(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    on_origin = git.resolve(repo.primary_path, "origin/main")
    (repo.primary_path / "local.txt").write_text("local\n")
    run_git("add", "local.txt", cwd=repo.primary_path)
    run_git("commit", "-qm", "Not pushed", cwd=repo.primary_path)
    run_git("checkout", "-q", "-b", "wip", cwd=repo.primary_path)
    (repo.primary_path / "wip.txt").write_text("wip\n")
    commit_everything(repo.primary_path, "wip")
    task = template_sync.apply(conn, settings, repo, create=["CLAUDE.md"], overwrite=[])
    assert task is not None and task.base_commit == on_origin


def test_apply_overwrites_only_the_picked_files(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    commit_the_template(settings, repo)
    (repo.primary_path / "CLAUDE.md").write_text("# Mine\n")
    (repo.primary_path / "logo.bin").write_bytes(b"mine")
    commit_everything(repo.primary_path, "Customise")
    task = template_sync.apply(conn, settings, repo, create=[], overwrite=["CLAUDE.md"])
    assert task is not None and task.worktree_path is not None
    assert (task.worktree_path / "CLAUDE.md").read_text() == "# sample\n"
    assert (task.worktree_path / "logo.bin").read_bytes() == b"mine"
    assert "- overwrite CLAUDE.md" in run_git("log", "-1", "--format=%B", cwd=task.worktree_path)


@pytest.mark.parametrize(
    ("create", "overwrite", "delete"),
    [
        (["README.md"], [], []),
        ([], ["CLAUDE.md"], []),
        (["../outside.md"], [], []),
        (["logo.bin", "nope.md"], [], []),
        ([], [], ["README.md"]),  # the repository's own, without the marker
        ([], [], ["CLAUDE.md"]),
        ([], [], ["nope.md"]),
    ],
)
def test_apply_refuses_files_the_plan_does_not_offer(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    create: list[str],
    overwrite: list[str],
    delete: list[str],
) -> None:
    with pytest.raises(TemplateSyncError, match="reload"):
        template_sync.apply(conn, settings, repo, create=create, overwrite=overwrite, delete=delete)
    assert tasks.list_for_repository(conn, repo) == []
    assert (repo.primary_path / "README.md").exists()


def test_a_sync_deletes_a_marked_file_the_template_retired_until_the_repository_is_ready(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    commit_the_template(settings, repo)
    commit_a_retired_file(repo)
    assert repositories.status(repo, settings) is repositories.Status.BEHIND
    task = template_sync.apply(conn, settings, repo, create=[], overwrite=[], delete=[RETIRED])
    assert task is not None and task.status is Status.COMPLETED and task.branch is not None
    assert task.worktree_path is not None and not (task.worktree_path / RETIRED).exists()
    assert committed_files(task.worktree_path) == [RETIRED]
    assert f"- delete {RETIRED}" in run_git("log", "-1", "--format=%B", cwd=task.worktree_path)
    assert (repo.primary_path / RETIRED).exists()  # the checkout is untouched
    run_git("push", "-q", "origin", f"{task.branch}:main", cwd=repo.primary_path)
    assert repositories.status(repo, settings) is repositories.Status.READY


def test_apply_starts_the_sync_from_the_commit_it_planned_with(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    remote_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit_the_template(settings, repo)
    commit_a_retired_file(repo)
    planned = run_git("rev-parse", "origin/main", cwd=repo.primary_path)
    create = worktrees.create

    def create_after_a_fetch(*args: object, **kwargs: object) -> worktrees.Worktree:
        """A fetch lands before the worktree is made, bringing the file unmarked."""
        clone = tmp_path / "elsewhere"
        run_git("clone", "-q", str(remote_repo), str(clone), cwd=tmp_path)
        (clone / RETIRED).write_text("# Design, now the repository's own\n")
        run_git("commit", "-qam", "Keep the rule as our own", cwd=clone)
        run_git("push", "-q", "origin", "main", cwd=clone)
        run_git("fetch", "-q", "origin", cwd=repo.primary_path)
        return create(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(worktrees, "create", create_after_a_fetch)
    task = template_sync.apply(conn, settings, repo, create=[], overwrite=[], delete=[RETIRED])
    assert task is not None and task.status is Status.COMPLETED
    assert task.base_commit == planned
    assert task.worktree_path is not None
    assert run_git("rev-parse", "HEAD~", cwd=task.worktree_path) == planned


def test_apply_fails_the_task_rather_than_write_through_a_symlink(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo.primary_path / ".claude").symlink_to(outside)
    commit_everything(repo.primary_path, "Symlinked .claude")
    task = template_sync.apply(
        conn, settings, repo, create=[".claude/skills/demo/run.sh"], overwrite=[]
    )
    assert task is not None and task.status is Status.FAILED
    assert "outside the worktree" in (task.error or "")
    assert list(outside.iterdir()) == []


def test_apply_fails_the_task_with_the_reason_when_the_commit_fails(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    hook = repo.primary_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'blocked by hook' >&2\nexit 1\n")
    hook.chmod(0o755)
    task = template_sync.apply(conn, settings, repo, create=["CLAUDE.md"], overwrite=[])
    assert task is not None and task.status is Status.FAILED
    assert "blocked by hook" in (task.error or "")
    assert task.worktree_path is not None and (task.worktree_path / "CLAUDE.md").exists()


# ---------------------------------------------------------------- file kinds

SETTINGS = ".claude/settings.json"


@pytest.mark.usefixtures("declared_kinds")
def test_apply_merges_the_picked_file_on_the_sync_branch(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    commit_the_template(settings, repo)
    (repo.primary_path / SETTINGS).write_text('{"permissions": {"allow": ["Bash(npm test)"]}}\n')
    commit_everything(repo.primary_path, "Customise")
    task = template_sync.apply(conn, settings, repo, create=[], overwrite=[], merge=[SETTINGS])
    assert task is not None and task.status is Status.COMPLETED
    assert task.worktree_path is not None
    assert json.loads((task.worktree_path / SETTINGS).read_text()) == {
        "permissions": {
            "allow": ["Bash(npm test)", "Bash(make check)"],
            "ask": ["Bash(git push:*)"],
        },
        "model": "sonnet",
    }
    assert committed_files(task.worktree_path) == [SETTINGS]
    assert f"- merge {SETTINGS}" in run_git("log", "-1", "--format=%B", cwd=task.worktree_path)


@pytest.mark.usefixtures("declared_kinds")
@pytest.mark.parametrize(
    ("overwrite", "merge"), [(["CLAUDE.md"], []), ([SETTINGS], []), ([], ["CLAUDE.md"])]
)
def test_apply_refuses_a_pick_the_files_kind_does_not_allow(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    overwrite: list[str],
    merge: list[str],
) -> None:
    commit_the_template(settings, repo)
    (repo.primary_path / "CLAUDE.md").write_text("# Mine\n")
    (repo.primary_path / SETTINGS).write_text("{}\n")
    commit_everything(repo.primary_path, "Customise")
    with pytest.raises(TemplateSyncError, match="reload"):
        template_sync.apply(conn, settings, repo, create=[], overwrite=overwrite, merge=merge)
    assert tasks.list_for_repository(conn, repo) == []


# ---------------------------------------------------------------- a sync waiting to land


def sync_missing(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, *paths: str
) -> tasks.Task:
    """A completed sync creating `paths`, or every missing file when none are named."""
    picked = list(paths) or [f.path for f in repositories.template_plan(repo, settings).missing]
    task = template_sync.apply(conn, settings, repo, create=picked, overwrite=[])
    assert task is not None and task.status is Status.COMPLETED and task.branch is not None
    return task


def test_a_completed_sync_waits_until_its_branch_lands_on_origin(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = sync_missing(conn, settings, repo)
    assert template_sync.waiting(conn, settings, repo) == task
    run_git("push", "-q", "origin", f"{task.branch}:main", cwd=repo.primary_path)
    assert template_sync.waiting(conn, settings, repo) is None


def test_a_sync_that_only_deletes_waits_until_it_lands(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    commit_the_template(settings, repo)
    commit_a_retired_file(repo)
    task = template_sync.apply(conn, settings, repo, create=[], overwrite=[], delete=[RETIRED])
    assert task is not None and task.branch is not None
    assert template_sync.waiting(conn, settings, repo) == task
    run_git("push", "-q", "origin", f"{task.branch}:main", cwd=repo.primary_path)
    assert template_sync.waiting(conn, settings, repo) is None
    assert template_sync.states(conn, settings, repo) == {
        task.id: template_sync.SyncState.ON_ORIGIN
    }


def test_a_landed_sync_doesnt_wait_on_a_marked_file_origin_gained_after_it(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    commit_the_template(settings, repo)
    commit_a_retired_file(repo)
    landed = template_sync.apply(conn, settings, repo, create=[], overwrite=[], delete=[RETIRED])
    assert landed is not None and landed.branch is not None
    run_git("push", "-q", "origin", f"{landed.branch}:main", cwd=repo.primary_path)
    run_git("merge", "-q", "--ff-only", "origin/main", cwd=repo.primary_path)
    copy = ".claude/rules/copy.md"  # e.g. another pull request copied a managed rule
    (repo.primary_path / copy).parent.mkdir(parents=True, exist_ok=True)
    (repo.primary_path / copy).write_text("<!-- managed by template -->\n# Copy\n")
    commit_everything(repo.primary_path, "Copy a managed rule")
    assert template_sync.waiting(conn, settings, repo) is None
    task = template_sync.apply(conn, settings, repo, create=[], overwrite=[], delete=[copy])
    assert task is not None and task.status is Status.COMPLETED


def test_a_sync_squash_merged_on_origin_no_longer_waits(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = sync_missing(conn, settings, repo)
    picked = [
        f.path
        for f in bootstrap.sync_plan(
            settings.template_dir, repo.primary_path, "main", "sample"
        ).missing
    ]
    run_git("restore", f"--source={task.branch}", "--", *picked, cwd=repo.primary_path)
    commit_everything(repo.primary_path, "Squashed sync")  # the same files, another commit
    assert template_sync.waiting(conn, settings, repo) is None


def test_a_sync_whose_worktree_is_gone_is_not_waiting(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = sync_missing(conn, settings, repo)
    assert task.worktree_path is not None
    run_git("worktree", "remove", "--force", str(task.worktree_path), cwd=repo.primary_path)
    assert template_sync.waiting(conn, settings, repo) is None


def test_a_sync_the_template_has_moved_past_is_not_waiting(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    sync_missing(conn, settings, repo, "CLAUDE.md")
    (settings.template_dir / "CLAUDE.md").write_text("# {{ repo_name }}, revised\n")
    assert template_sync.waiting(conn, settings, repo) is None


def test_apply_is_refused_while_a_sync_waits(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = sync_missing(conn, settings, repo, "CLAUDE.md")
    with pytest.raises(TemplateSyncError, match=rf"sync #{task.id} on {task.branch} is waiting"):
        template_sync.apply(conn, settings, repo, create=["logo.bin"], overwrite=[])
    assert len(tasks.list_for_repository(conn, repo)) == 1


# ---------------------------------------------------------------- sync states, and removing one


def test_states_tell_a_waiting_sync_from_one_on_origin_and_one_not(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    first = sync_missing(conn, settings, repo, "CLAUDE.md")
    run_git("push", "-q", "origin", f"{first.branch}:main", cwd=repo.primary_path)
    second = sync_missing(conn, settings, repo, "logo.bin")
    assert template_sync.states(conn, settings, repo) == {
        first.id: template_sync.SyncState.ON_ORIGIN,
        second.id: template_sync.SyncState.WAITING,
    }
    (settings.template_dir / "logo.bin").write_bytes(b"revised")  # the template moved past it
    assert template_sync.states(conn, settings, repo)[second.id] is (
        template_sync.SyncState.NOT_ON_ORIGIN
    )


def test_remove_deletes_a_syncs_branch_and_worktree_and_says_so_in_its_state(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = sync_missing(conn, settings, repo, "CLAUDE.md")
    template_sync.remove(conn, settings, task)
    assert task.worktree_path is not None and not task.worktree_path.exists()
    assert not git.branch_exists(repo.primary_path, task.branch or "")
    assert template_sync.states(conn, settings, repo) == {task.id: template_sync.SyncState.REMOVED}
    assert template_sync.waiting(conn, settings, repo) is None  # its picks are offered again
    assert repositories.template_plan(repo, settings).missing


def test_remove_refuses_a_task_that_is_not_a_completed_sync(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = sync_missing(conn, settings, repo, "CLAUDE.md")
    template_sync.remove(conn, settings, task)
    with pytest.raises(TemplateSyncError, match="has no worktree to remove"):
        template_sync.remove(conn, settings, task)
    other = tasks.create(conn, repo.id, "implement")
    with pytest.raises(TemplateSyncError, match="isn't a completed template sync"):
        template_sync.remove(conn, settings, other)
