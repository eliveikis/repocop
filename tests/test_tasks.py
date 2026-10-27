"""Tasks: start a workflow on a requirement in its worktree, one active task at a time."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from repocop import db
from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import (
    claude,
    git,
    pull_requests,
    repositories,
    requirements,
    tasks,
    worktrees,
)
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement
from repocop.services.tasks import Status, Task, TaskError
from tests.conftest import recorded_requirement, run_git


def commit_skills(checkout: Path, *names: str) -> None:
    for name in names:
        folder = checkout / ".claude" / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=checkout)
    run_git("commit", "-qm", "Add skills", cwd=checkout)


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    repository = repositories.register(conn, settings, str(remote_repo)).repository
    commit_skills(repository.primary_path, "implement", "review-requirement")
    return repository


def new_requirement(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    name: str = "bulk-user-import",
) -> Requirement:
    return recorded_requirement(conn, settings, repo, f"{name}.md")


# ---------------------------------------------------------------- workflows


def test_workflows_are_the_skills_committed_at_head(settings: Settings, repo: Repository) -> None:
    uncommitted = repo.primary_path / ".claude" / "skills" / "draft"
    uncommitted.mkdir()
    (uncommitted / "SKILL.md").write_text("# draft\n")
    assert tasks.workflows(settings, repo) == ["implement", "review-requirement"]


def test_workflows_skip_folders_without_a_usable_name(settings: Settings, repo: Repository) -> None:
    commit_skills(repo.primary_path, "Bad_Name")
    assert "Bad_Name" not in tasks.workflows(settings, repo)


# ---------------------------------------------------------------- start


def test_start_creates_the_requirements_worktree_and_a_queued_task(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    head = git.head_commit(repo.primary_path)
    task = tasks.start(conn, settings, requirement, "implement")
    assert task.status is Status.QUEUED
    assert (task.workflow, task.requirement_id, task.repository_id) == (
        "implement",
        requirement.id,
        repo.id,
    )
    assert task.branch == "agent/bulk-user-import"
    assert task.worktree_path == settings.worktrees_root / "sample" / "bulk-user-import"
    assert task.base_commit == head
    assert (task.worktree_path / requirement.path).read_text() == "Import users.\n"
    assert tasks.get(conn, task.id) == task


def test_start_records_a_hand_made_file_and_names_its_branch_after_the_file(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    folder = repo.primary_path / "specs/changes/todo"
    folder.mkdir(parents=True)
    (folder / "search-notes.md").write_text("Faster search.\n")
    run_git("add", ".", cwd=repo.primary_path)
    run_git("commit", "-qm", "Add search-notes", cwd=repo.primary_path)
    found = requirements.find(conn, settings, repo, "search-notes.md")
    assert found is not None and found.id is None
    task = tasks.start(conn, settings, found, "implement")
    [recorded] = requirements.list_for(conn, repo)
    assert (recorded.path, task.requirement_id) == (found.path, recorded.id)
    assert task.branch == "agent/search-notes"
    assert task.worktree_path == settings.worktrees_root / "sample" / "search-notes"


def test_start_keeps_the_branch_name_of_a_requirement_recorded_under_an_id(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    folder = repo.primary_path / "specs/changes/todo"
    folder.mkdir(parents=True)
    (folder / "req-7-search.md").write_text("Faster search.\n")
    run_git("add", ".", cwd=repo.primary_path)
    run_git("commit", "-qm", "Add req-7-search", cwd=repo.primary_path)
    conn.execute(
        "INSERT INTO requirements (id, repository_id, path, created_at, updated_at)"
        " VALUES (7, ?, 'specs/changes/todo/req-7-search.md', '', '')",
        (repo.id,),
    )
    found = requirements.find(conn, settings, repo, "req-7-search.md")
    assert found is not None
    task = tasks.start(conn, settings, found, "implement")
    assert (task.requirement_id, task.branch) == (7, "agent/req-7-search")


def test_start_refuses_a_file_name_git_wont_take_as_a_branch_and_records_nothing(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    folder = repo.primary_path / "specs/changes/todo"
    folder.mkdir(parents=True)
    (folder / "ends-with-a-dot..md").write_text("Something.\n")
    run_git("add", ".", cwd=repo.primary_path)
    run_git("commit", "-qm", "Add it", cwd=repo.primary_path)
    found = requirements.find(conn, settings, repo, "ends-with-a-dot..md")
    assert found is not None
    with pytest.raises(RepoCopError, match=r"agent/ends-with-a-dot\."):
        tasks.start(conn, settings, found, "implement")
    assert requirements.list_for(conn, repo) == []
    assert not (settings.worktrees_root / "sample" / "ends-with-a-dot.").exists()


def test_start_leaves_the_primary_checkout_untouched(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    head = git.head_commit(repo.primary_path)
    tasks.start(conn, settings, requirement, "implement")
    assert git.current_branch(repo.primary_path) == "main"
    assert git.head_commit(repo.primary_path) == head
    assert run_git("status", "--porcelain", cwd=repo.primary_path) == ""


def test_start_records_the_queued_status_as_an_event(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = tasks.start(conn, settings, new_requirement(conn, settings, repo), "implement")
    rows = conn.execute(
        "SELECT seq, kind, payload_json FROM task_events WHERE task_id = ?", (task.id,)
    )
    assert [(r["seq"], r["kind"], json.loads(r["payload_json"])) for r in rows] == [
        (1, "status_change", {"status": "queued"})
    ]


def test_start_refuses_a_requirement_with_uncommitted_changes(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    (repo.primary_path / requirement.path).write_text("# Bulk user import\n\nEdited by hand.\n")
    commit_first = "uncommitted changes. Commit specs/changes/todo/bulk-user-import.md first"
    with pytest.raises(TaskError, match=commit_first):
        tasks.start(conn, settings, requirement, "implement")
    assert not (settings.worktrees_root / "sample").exists()
    assert tasks.list_for_requirement(conn, requirement) == []


def test_start_refuses_a_second_active_task_on_the_requirement(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    first = tasks.start(conn, settings, requirement, "review-requirement")
    with pytest.raises(TaskError, match=f"#{first.id}"):
        tasks.start(conn, settings, requirement, "implement")


def test_start_waits_while_the_requirements_starts_are_held(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    started: list[Task] = []

    def start() -> None:
        own = db.connect(settings.database_path)
        try:
            started.append(tasks.start(own, settings, requirement, "implement"))
        finally:
            own.close()

    starter = threading.Thread(target=start)
    with tasks.hold_starts(requirement):
        starter.start()
        starter.join(timeout=0.5)
        assert tasks.active_task(conn, requirement) is None
    starter.join(timeout=10)
    assert [task.status for task in started] == [Status.QUEUED]


def test_start_does_not_wait_for_another_requirements_held_starts(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    held = new_requirement(conn, settings, repo)
    other = new_requirement(conn, settings, repo, name="login-crash")
    with tasks.hold_starts(held):
        assert tasks.start(conn, settings, other, "implement").status is Status.QUEUED


def test_start_after_cancelling_reuses_the_worktree_branch_and_base(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    first = tasks.start(conn, settings, requirement, "review-requirement")
    tasks.cancel(conn, first)
    (repo.primary_path / "later.txt").write_text("the human keeps working\n")
    run_git("add", "later.txt", cwd=repo.primary_path)
    run_git("commit", "-qm", "Later work", cwd=repo.primary_path)
    second = tasks.start(conn, settings, requirement, "implement")
    assert (second.branch, second.worktree_path, second.base_commit) == (
        first.branch,
        first.worktree_path,
        first.base_commit,
    )


def test_start_refuses_when_the_reused_worktree_is_gone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    requirement = new_requirement(conn, settings, repo)
    first = tasks.start(conn, settings, requirement, "review-requirement")
    tasks.cancel(conn, first)
    assert first.worktree_path is not None
    first.worktree_path.rename(tmp_path / "moved-away")
    with pytest.raises(TaskError, match="gone"):
        tasks.start(conn, settings, requirement, "implement")


def test_start_refuses_an_archived_requirement(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    (repo.primary_path / "specs/changes/archive").mkdir()
    run_git("mv", requirement.path, "specs/changes/archive/", cwd=repo.primary_path)
    run_git("commit", "-qm", "Archive", cwd=repo.primary_path)
    with pytest.raises(TaskError, match="archived"):
        tasks.start(conn, settings, requirement, "implement")


def test_start_refuses_a_workflow_that_is_not_a_committed_skill(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    with pytest.raises(TaskError, match="skill"):
        tasks.start(conn, settings, requirement, "deploy-to-prod")
    assert not (settings.worktrees_root / "sample").exists()


def test_start_refuses_a_branch_repocop_did_not_create(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    run_git("branch", "agent/bulk-user-import", cwd=repo.primary_path)
    with pytest.raises(RepoCopError, match="already exists"):
        tasks.start(conn, settings, requirement, "implement")
    assert tasks.list_for_requirement(conn, requirement) == []


def test_tasks_on_two_requirements_get_separate_worktrees(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    first = tasks.start(
        conn, settings, new_requirement(conn, settings, repo, name="First"), "implement"
    )
    second = tasks.start(
        conn, settings, new_requirement(conn, settings, repo, name="Second"), "implement"
    )
    assert first.worktree_path is not None and second.worktree_path is not None
    (first.worktree_path / "change.txt").write_text("only in the first\n")
    assert first.worktree_path != second.worktree_path
    assert not (second.worktree_path / "change.txt").exists()
    assert run_git("status", "--porcelain", cwd=second.worktree_path) == ""


# ---------------------------------------------------------------- cancel and lookups


def test_cancel_ends_a_queued_task_and_records_it(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    task = tasks.cancel(conn, tasks.start(conn, settings, requirement, "implement"))
    assert task.status is Status.CANCELLED
    assert tasks.active_task(conn, requirement) is None
    kinds = conn.execute(
        "SELECT seq, payload_json FROM task_events WHERE task_id = ? ORDER BY seq", (task.id,)
    )
    assert [json.loads(r["payload_json"])["status"] for r in kinds] == ["queued", "cancelled"]


def test_cancel_refuses_a_task_that_is_not_queued(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = tasks.start(conn, settings, new_requirement(conn, settings, repo), "implement")
    conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task.id,))
    completed = tasks.get(conn, task.id)
    assert completed is not None
    with pytest.raises(TaskError, match="completed"):
        tasks.cancel(conn, completed)


def test_list_for_requirement_returns_its_tasks_newest_first(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    first = tasks.cancel(conn, tasks.start(conn, settings, requirement, "review-requirement"))
    second = tasks.start(conn, settings, requirement, "implement")
    assert [t.id for t in tasks.list_for_requirement(conn, requirement)] == [second.id, first.id]


def test_get_returns_none_for_an_unknown_id(conn: sqlite3.Connection) -> None:
    assert tasks.get(conn, 999) is None


# ---------------------------------------------------------------- status machine and events


def queued_task(conn: sqlite3.Connection, settings: Settings, repo: Repository) -> tasks.Task:
    return tasks.start(conn, settings, new_requirement(conn, settings, repo), "implement")


@pytest.mark.parametrize(
    "path",
    [
        ["running", "waiting_for_user", "running", "waiting_for_user", "completed"],
        ["running", "failed"],
        ["running", "cancelled"],
        ["running", "waiting_for_user", "cancelled"],
        ["failed"],
    ],
)
def test_transition_follows_the_status_machine(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, path: list[str]
) -> None:
    task = queued_task(conn, settings, repo)
    for status in path:
        task = tasks.transition(conn, task.id, Status(status))
    assert task.status is Status(path[-1])


@pytest.mark.parametrize(
    ("path", "illegal"),
    [
        ([], "waiting_for_user"),
        ([], "completed"),
        (["running", "cancelled"], "running"),
        (["running", "failed"], "waiting_for_user"),
    ],
)
def test_transition_refuses_moves_the_machine_does_not_allow(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, path: list[str], illegal: str
) -> None:
    task = queued_task(conn, settings, repo)
    for status in path:
        task = tasks.transition(conn, task.id, Status(status))
    with pytest.raises(TaskError, match="can't go"):
        tasks.transition(conn, task.id, Status(illegal))


def test_transition_to_failed_records_the_error(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    failed = tasks.transition(conn, task.id, Status.FAILED, error="boom")
    assert failed.error == "boom"
    last = tasks.events_after(conn, task.id, 0)[-1]
    assert (last.kind, last.payload) == ("status_change", {"status": "failed", "error": "boom"})


def test_record_appends_events_in_order(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    tasks.record(conn, task.id, "assistant_text", {"text": "hello"})
    tasks.record(conn, task.id, "tool_use", {"name": "Read"})
    events = tasks.events_after(conn, task.id, 1)
    assert [(e.seq, e.kind) for e in events] == [(2, "assistant_text"), (3, "tool_use")]


def test_set_session_stores_the_first_session_id_only(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    tasks.set_session(conn, task.id, "session-1")
    tasks.set_session(conn, task.id, "session-2")
    stored = tasks.get(conn, task.id)
    assert stored is not None and stored.claude_session_id == "session-1"


def test_mark_done_completes_a_waiting_task(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    waiting = tasks.transition(conn, task.id, Status.WAITING_FOR_USER)
    assert tasks.mark_done(conn, waiting).status is Status.COMPLETED


def test_mark_done_refuses_a_task_that_is_not_waiting(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    with pytest.raises(TaskError, match="waiting"):
        tasks.mark_done(conn, task)


def test_cancel_also_ends_a_waiting_task(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    tasks.transition(conn, task.id, Status.RUNNING)
    waiting = tasks.transition(conn, task.id, Status.WAITING_FOR_USER)
    assert tasks.cancel(conn, waiting).status is Status.CANCELLED


def test_set_process_records_and_clears_the_session_process(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    tasks.set_process(conn, task.id, 4242, "123456")
    recorded = tasks.get(conn, task.id)
    assert recorded is not None and (recorded.session_pid, recorded.session_pid_start) == (
        4242,
        "123456",
    )
    tasks.set_process(conn, task.id, None, None)
    cleared = tasks.get(conn, task.id)
    assert cleared is not None and (cleared.session_pid, cleared.session_pid_start) == (None, None)


def test_transition_can_carry_details_in_its_event(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    tasks.transition(
        conn, task.id, Status.FAILED, error="boom", details={"interrupted": {"commits": 2}}
    )
    last = tasks.events_after(conn, task.id, 0)[-1]
    assert last.payload == {"status": "failed", "error": "boom", "interrupted": {"commits": 2}}


def test_start_again_queues_the_same_workflow_in_the_same_worktree(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    first = tasks.cancel(conn, queued_task(conn, settings, repo))
    again = tasks.start_again(conn, settings, first)
    assert again.id != first.id
    assert (again.workflow, again.requirement_id, again.status) == ("implement", 1, Status.QUEUED)
    assert (again.worktree_path, again.branch, again.base_commit) == (
        first.worktree_path,
        first.branch,
        first.base_commit,
    )


def test_start_again_refuses_a_task_that_did_not_end_early(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    with pytest.raises(TaskError, match="failed or cancelled"):
        tasks.start_again(conn, settings, task)


def waiting_task(conn: sqlite3.Connection, settings: Settings, requirement: Requirement) -> Task:
    task = tasks.start(conn, settings, requirement, "implement")
    tasks.set_session(conn, task.id, f"session-{task.id}")
    tasks.transition(conn, task.id, Status.RUNNING)
    return tasks.transition(conn, task.id, Status.WAITING_FOR_USER)


def test_resume_command_is_offered_once_the_task_has_ended(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    waiting = waiting_task(conn, settings, new_requirement(conn, settings, repo))
    assert tasks.resume_command(conn, settings, waiting) is None
    done = tasks.mark_done(conn, waiting)
    assert done.worktree_path is not None
    assert tasks.resume_command(conn, settings, done) == claude.resume_command(
        settings, done.worktree_path, "session-1"
    )


def test_resume_command_waits_while_another_task_is_active_in_the_worktree(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    done = tasks.mark_done(conn, waiting_task(conn, settings, requirement))
    tasks.start(conn, settings, requirement, "review-requirement")
    assert tasks.resume_command(conn, settings, done) is None


def test_resume_command_is_none_once_the_worktree_is_gone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    requirement = new_requirement(conn, settings, repo)
    done = tasks.mark_done(conn, waiting_task(conn, settings, requirement))
    assert done.worktree_path is not None
    done.worktree_path.rename(tmp_path / "moved-away")
    assert tasks.resume_command(conn, settings, done) is None


def test_resume_command_needs_a_session(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    cancelled = tasks.cancel(conn, queued_task(conn, settings, repo))
    assert tasks.resume_command(conn, settings, cancelled) is None


def test_worktree_changes_shows_what_the_task_changed(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = queued_task(conn, settings, repo)
    assert task.worktree_path is not None
    (task.worktree_path / "notes.txt").write_text("a new note\n")
    changes = tasks.worktree_changes(conn, settings, task)
    assert changes is not None and "+a new note" in changes.diff


def test_worktree_changes_is_none_once_the_worktree_is_gone(
    conn: sqlite3.Connection, settings: Settings, repo: Repository, tmp_path: Path
) -> None:
    task = queued_task(conn, settings, repo)
    assert task.worktree_path is not None
    task.worktree_path.rename(tmp_path / "moved-away")
    assert tasks.worktree_changes(conn, settings, task) is None


def test_create_queues_a_task_without_a_requirement_or_worktree(
    conn: sqlite3.Connection, repo: Repository
) -> None:
    task = tasks.create(conn, repo.id, "template-sync")
    assert (task.workflow, task.requirement_id, task.status, task.worktree_path) == (
        "template-sync",
        None,
        Status.QUEUED,
        None,
    )


def test_set_worktree_records_where_a_task_works(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    task = tasks.create(conn, repo.id, "template-sync")
    path = settings.worktrees_root / "sample" / f"template-sync-{task.id}"
    updated = tasks.set_worktree(conn, task.id, "chore/template-sync-1", path, "abc123")
    assert (updated.branch, updated.worktree_path, updated.base_commit) == (
        "chore/template-sync-1",
        path,
        "abc123",
    )


def test_list_for_repository_filters_by_workflow_newest_first(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    first = tasks.create(conn, repo.id, "template-sync")
    queued_task(conn, settings, repo)
    second = tasks.create(conn, repo.id, "template-sync")
    listed = tasks.list_for_repository(conn, repo, workflow="template-sync")
    assert [task.id for task in listed] == [second.id, first.id]


# ---------------------------------------------------------------- RepoCop's own workflows

OWN_WORKFLOW = "Own workflow"  # not a name a skill can have


def test_start_on_branch_is_refused_before_the_requirements_first_task(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    with pytest.raises(TaskError, match="bulk-user-import has no branch yet"):
        tasks.start_on_branch(conn, settings, requirement, OWN_WORKFLOW)


def test_start_on_branch_queues_a_workflow_no_skill_backs_in_the_requirements_worktree(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    first = tasks.start(conn, settings, requirement, "implement")
    tasks.cancel(conn, first)
    task = tasks.start_on_branch(conn, settings, requirement, OWN_WORKFLOW)
    assert task.workflow == OWN_WORKFLOW and task.status is Status.QUEUED
    assert (task.branch, task.worktree_path, task.base_commit) == (
        first.branch,
        first.worktree_path,
        first.base_commit,
    )


def test_start_on_branch_is_refused_while_another_task_is_active(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    tasks.start(conn, settings, requirement, "implement")
    with pytest.raises(TaskError, match=r"task #1 \(implement\) is still queued"):
        tasks.start_on_branch(conn, settings, requirement, OWN_WORKFLOW)


def test_start_refuses_a_workflow_of_repocops_own(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    with pytest.raises(TaskError, match="isn't a skill committed"):
        tasks.start(conn, settings, requirement, OWN_WORKFLOW)


def test_start_again_starts_a_workflow_of_repocops_own_on_the_branch_again(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    requirement = new_requirement(conn, settings, repo)
    tasks.cancel(conn, tasks.start(conn, settings, requirement, "implement"))
    own = tasks.cancel(conn, tasks.start_on_branch(conn, settings, requirement, OWN_WORKFLOW))
    again = tasks.start_again(conn, settings, own)
    assert again.workflow == OWN_WORKFLOW and again.worktree_path == own.worktree_path


# ---------------------------------------------------------------- branch names


def test_a_requirements_new_branch_is_an_agent_branch_named_for_it(
    conn: sqlite3.Connection, settings: Settings, repo: Repository
) -> None:
    feature = new_requirement(conn, settings, repo)
    fix = new_requirement(conn, settings, repo, name="login-crash")
    assert tasks.start(conn, settings, feature, "implement").branch == "agent/bulk-user-import"
    assert tasks.start(conn, settings, fix, "implement").branch == "agent/login-crash"


def test_a_requirement_keeps_a_branch_named_the_old_way(
    conn: sqlite3.Connection,
    settings: Settings,
    repo: Repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = new_requirement(conn, settings, repo)
    with monkeypatch.context() as earlier:  # a branch made before agent/ names
        earlier.setattr(
            worktrees,
            "requirement_names",
            lambda name: (f"req-1-{name}", f"feature/req-1-{name}"),
        )
        first = tasks.start(conn, settings, requirement, "implement")
    tasks.cancel(conn, first)
    later = tasks.start(conn, settings, requirement, "implement")
    assert later.branch == first.branch == "feature/req-1-bulk-user-import"
    assert later.worktree_path == first.worktree_path
    assert pull_requests.of_requirement(conn, settings, requirement).branch == later.branch
    tasks.cancel(conn, later)
    own = tasks.start_on_branch(conn, settings, requirement, "Own workflow")  # as a review starts
    assert own.branch == "feature/req-1-bulk-user-import"
