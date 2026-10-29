"""Pull requests: open one for a completed template sync's branch, push to it, ask for a
review, and every refusal."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import pull_requests, repositories, tasks, template_sync
from repocop.services.pull_requests import Action, PullRequestError
from repocop.services.repositories import Repository
from repocop.services.tasks import Status, Task
from tests.conftest import run_git
from tests.fakes.fake_gh import FakeGh

BRANCH = "agent/template-sync-1"
PULL = "https://github.com/owner/sample/pull/1"


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, github_checkout: Path) -> Repository:
    """Repository `sample`, registered with its github.com remote."""
    return repositories.register(conn, settings, "", "sample", default_branch="main").repository


def completed_sync(conn: sqlite3.Connection, settings: Settings, repo: Repository) -> Task:
    """A completed template sync that created CLAUDE.md on its branch."""
    task = template_sync.apply(conn, settings, repo, create=["CLAUDE.md"], overwrite=[])
    assert task is not None
    assert task.status is Status.COMPLETED
    return task


@pytest.fixture
def sync(conn: sqlite3.Connection, settings: Settings, repo: Repository) -> Task:
    return completed_sync(conn, settings, repo)


def worktree(settings: Settings, name: str = "template-sync-1") -> Path:
    return settings.worktrees_root / "sample" / name


def commit_in(folder: Path, name: str = "work.txt") -> str:
    (folder / name).write_text("work\n")
    run_git("add", name, cwd=folder)
    run_git("commit", "-qm", f"Add {name}", cwd=folder)
    return run_git("rev-parse", "HEAD", cwd=folder)


def sync_head(settings: Settings) -> str:
    return run_git("rev-parse", "HEAD", cwd=worktree(settings))


def remote_branches(remote: Path) -> list[str]:
    return run_git("for-each-ref", "--format=%(refname:short)", cwd=remote).splitlines()


def act(
    conn: sqlite3.Connection, settings: Settings, sync: Task, action: Action
) -> pull_requests.PullRequest:
    return pull_requests.perform(conn, settings, pull_requests.of_sync(conn, sync), action)


# ---------------------------------------------------------------- actions


def test_open_makes_origin_the_branchs_upstream(
    conn: sqlite3.Connection, settings: Settings, sync: Task, fake_gh: FakeGh
) -> None:
    act(conn, settings, sync, Action.OPEN)
    upstream = run_git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=worktree(settings))
    assert upstream == f"origin/{BRANCH}"


def test_push_sends_new_commits_to_the_pull_requests_branch(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
) -> None:
    act(conn, settings, sync, Action.OPEN)
    head = commit_in(worktree(settings))
    calls = len(fake_gh.calls)
    assert act(conn, settings, sync, Action.PUSH).url == PULL
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == head
    assert [call[:2] for call in fake_gh.calls[calls:] if call[0] == "pr"] == [["pr", "list"]]


def test_review_asks_copilot_to_review_the_stored_pull_request(
    conn: sqlite3.Connection, settings: Settings, sync: Task, fake_gh: FakeGh
) -> None:
    act(conn, settings, sync, Action.OPEN)
    act(conn, settings, sync, Action.REVIEW)
    assert fake_gh.calls[-1] == ["pr", "edit", PULL, "--add-reviewer", "@copilot"]


def test_open_pushes_the_syncs_branch_and_opens_a_pull_request_listing_its_files(
    conn: sqlite3.Connection, settings: Settings, sync: Task, remote_repo: Path, fake_gh: FakeGh
) -> None:
    opened = act(conn, settings, sync, Action.OPEN)
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == sync_head(settings)
    created = fake_gh.calls[-1]
    assert created[created.index("--head") + 1] == "agent/template-sync-1"
    assert created[created.index("--title") + 1] == "Sync with the repo template"
    assert created[created.index("--body") + 1] == "Files changed:\n\n- `CLAUDE.md`\n"
    assert pull_requests.get(conn, sync.repository_id, "agent/template-sync-1") == opened


# ---------------------------------------------------------------- refusals


def test_a_sync_that_did_not_complete_is_refused(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    failed = tasks.create(conn, repo.id, template_sync.WORKFLOW)
    tasks.transition(conn, failed.id, Status.FAILED, error="boom")
    with pytest.raises(PullRequestError, match="template sync #1 is failed"):
        pull_requests.of_sync(conn, tasks.get(conn, failed.id) or failed)


@pytest.mark.parametrize("action", list(Action))
def test_actions_are_refused_while_the_worktree_has_uncommitted_changes(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
    action: Action,
) -> None:
    (worktree(settings) / "draft.txt").write_text("not committed\n")
    with pytest.raises(PullRequestError, match="1 file with uncommitted changes"):
        act(conn, settings, sync, action)
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


@pytest.mark.parametrize("action", list(Action))
def test_actions_are_refused_when_origin_is_not_a_github_remote(
    conn: sqlite3.Connection,
    settings: Settings,
    primary_checkout: Path,
    remote_repo: Path,
    fake_gh: FakeGh,
    action: Action,
) -> None:
    repo = repositories.register(conn, settings, str(remote_repo), default_branch="main").repository
    sync = completed_sync(conn, settings, repo)
    with pytest.raises(RepoCopError, match=r"isn't a repository on github\.com"):
        act(conn, settings, sync, action)
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


@pytest.mark.parametrize(
    "push_urls",
    [
        ["git@github.com:someone/fork.git"],
        ["https://gitlab.com/owner/sample.git"],
        ["git@github.com:owner/sample.git", "git@github.com:owner/mirror.git"],
    ],
)
@pytest.mark.parametrize("action", list(Action))
def test_actions_are_refused_when_origin_pushes_to_another_repository(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
    action: Action,
    push_urls: list[str],
) -> None:
    for url in push_urls:
        run_git("remote", "set-url", "--push", "--add", "origin", url, cwd=repo.primary_path)
    with pytest.raises(PullRequestError, match=f"origin pushes to .*{push_urls[-1]}"):
        act(conn, settings, sync, action)
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


def test_origin_may_push_to_another_spelling_of_the_same_repository(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
) -> None:
    same = "ssh://git@github.com/owner/sample"
    run_git("remote", "set-url", "--push", "origin", same, cwd=repo.primary_path)
    assert act(conn, settings, sync, Action.OPEN).url == PULL
    assert BRANCH in remote_branches(remote_repo)


@pytest.mark.parametrize("action", list(Action))
def test_actions_are_refused_when_gh_is_not_installed(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: Action,
) -> None:
    only_git = tmp_path / "only-git"
    only_git.mkdir()
    (only_git / "git").symlink_to(shutil.which("git") or "")
    monkeypatch.setenv("PATH", str(only_git))
    with pytest.raises(RepoCopError, match=r"GitHub CLI \(gh\) isn't installed"):
        act(conn, settings, sync, action)
    assert remote_branches(remote_repo) == ["main"]


@pytest.mark.parametrize("action", list(Action))
def test_actions_are_refused_when_gh_is_logged_out(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
    action: Action,
) -> None:
    fake_gh.log_out()
    with pytest.raises(RepoCopError, match=r"isn't logged in to github\.com"):
        act(conn, settings, sync, action)
    assert remote_branches(remote_repo) == ["main"]
    assert not [call for call in fake_gh.calls if call[0] == "pr"]


def test_open_is_refused_when_the_branch_has_a_pull_request_and_remembers_it(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
) -> None:
    existing = "https://github.com/owner/sample/pull/41"
    fake_gh.add_pull_request(BRANCH, existing)
    with pytest.raises(PullRequestError, match=f"already has an open pull request: {existing}"):
        act(conn, settings, sync, Action.OPEN)
    assert remote_branches(remote_repo) == ["main"]
    assert not [call for call in fake_gh.calls if call[:2] == ["pr", "create"]]
    stored = pull_requests.get(conn, repo.id, BRANCH)
    assert stored is not None
    assert stored.url == existing


@pytest.mark.parametrize("action", [Action.PUSH, Action.REVIEW])
def test_push_and_review_are_refused_before_a_pull_request_is_opened(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
    action: Action,
) -> None:
    with pytest.raises(PullRequestError, match=r"has no open pull request\. Open one first"):
        act(conn, settings, sync, action)
    assert remote_branches(remote_repo) == ["main"]


def test_push_is_refused_when_the_remote_branch_has_other_commits(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    tmp_path: Path,
    fake_gh: FakeGh,
) -> None:
    act(conn, settings, sync, Action.OPEN)
    run_git("clone", "-q", "-b", BRANCH, str(remote_repo), "other", cwd=tmp_path)
    theirs = commit_in(tmp_path / "other", "theirs.txt")
    run_git("push", "-q", "origin", BRANCH, cwd=tmp_path / "other")
    commit_in(worktree(settings))
    with pytest.raises(RepoCopError, match="has commits this branch doesn't"):
        act(conn, settings, sync, Action.PUSH)
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == theirs


def test_actions_are_refused_when_the_worktree_is_gone(
    conn: sqlite3.Connection, settings: Settings, sync: Task, fake_gh: FakeGh
) -> None:
    shutil.rmtree(worktree(settings))
    with pytest.raises(PullRequestError, match="is gone"):
        act(conn, settings, sync, Action.OPEN)
    assert fake_gh.calls == []


def test_actions_are_refused_when_the_worktree_is_on_another_branch(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
) -> None:
    run_git("checkout", "-q", "-b", "elsewhere", cwd=worktree(settings))
    with pytest.raises(PullRequestError, match=f"is on elsewhere, not {BRANCH}"):
        act(conn, settings, sync, Action.OPEN)
    assert remote_branches(remote_repo) == ["main"]
    assert fake_gh.calls == []


def test_open_replaces_a_remembered_pull_request_that_is_no_longer_open(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    sync: Task,
    fake_gh: FakeGh,
) -> None:
    fake_gh.add_pull_request(BRANCH, "https://github.com/owner/sample/pull/41")
    with pytest.raises(PullRequestError, match="already has an open pull request"):
        act(conn, settings, sync, Action.OPEN)
    fake_gh.close_pull_requests()
    assert act(conn, settings, sync, Action.OPEN).url == PULL
    stored = pull_requests.get(conn, repo.id, BRANCH)
    assert stored is not None
    assert stored.url == PULL


@pytest.mark.parametrize("action", [Action.PUSH, Action.REVIEW])
def test_push_and_review_are_refused_once_the_pull_request_is_merged_or_closed(
    conn: sqlite3.Connection,
    settings: Settings,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
    action: Action,
) -> None:
    act(conn, settings, sync, Action.OPEN)
    pushed = run_git("rev-parse", BRANCH, cwd=remote_repo)
    fake_gh.close_pull_requests()
    commit_in(worktree(settings))
    with pytest.raises(PullRequestError, match=f"{PULL} is no longer open on GitHub"):
        act(conn, settings, sync, action)
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == pushed
    assert not [call for call in fake_gh.calls if call[:2] == ["pr", "edit"]]


def test_a_new_pull_request_opens_after_the_last_one_was_merged(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
) -> None:
    act(conn, settings, sync, Action.OPEN)
    fake_gh.close_pull_requests()
    head = commit_in(worktree(settings))
    second = act(conn, settings, sync, Action.OPEN)
    assert second.url == "https://github.com/owner/sample/pull/2"
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == head
    assert pull_requests.get(conn, repo.id, BRANCH) == second


def test_push_and_review_use_a_pull_request_opened_on_github(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    sync: Task,
    remote_repo: Path,
    fake_gh: FakeGh,
) -> None:
    by_hand = "https://github.com/owner/sample/pull/41"
    fake_gh.add_pull_request(BRANCH, by_hand)
    head = commit_in(worktree(settings))
    assert act(conn, settings, sync, Action.PUSH).url == by_hand
    assert run_git("rev-parse", BRANCH, cwd=remote_repo) == head
    act(conn, settings, sync, Action.REVIEW)
    assert fake_gh.calls[-1] == ["pr", "edit", by_hand, "--add-reviewer", "@copilot"]
    stored = pull_requests.get(conn, repo.id, BRANCH)
    assert stored is not None
    assert stored.url == by_hand
