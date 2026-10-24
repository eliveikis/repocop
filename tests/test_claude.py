"""Claude boundary: sessions only in RepoCop worktrees, SDK messages turned into updates."""

import os
import signal
import sqlite3
import subprocess
from contextlib import aclosing
from pathlib import Path

import pytest
from pydantic import SecretStr

from repocop.config import Settings
from repocop.services import claude, repositories, worktrees
from repocop.services.claude import ClaudeError, Event, SessionStarted, TurnEnded
from repocop.services.repositories import Repository
from tests.conftest import kill_process, process_gone, run_git
from tests.fakes.fake_claude import THINKING, FakeClaudeFactory

REQUIREMENT = "specs/req.md"


@pytest.fixture
def repo(conn: sqlite3.Connection, settings: Settings, remote_repo: Path) -> Repository:
    repository = repositories.register(conn, settings, str(remote_repo)).repository
    skill = repository.primary_path / ".claude" / "skills" / "implement"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# implement\n")
    (repository.primary_path / "specs").mkdir()
    (repository.primary_path / REQUIREMENT).write_text("# Req\n\nDo it.\n")
    run_git("add", ".", cwd=repository.primary_path)
    run_git("commit", "-qm", "skill and requirement", cwd=repository.primary_path)
    return repository


@pytest.fixture
def worktree(settings: Settings, repo: Repository) -> Path:
    return worktrees.create(repo, settings, "req-1-x", "feature/req-1-x").path


async def turn(session: claude.Session, prompt: str) -> list[claude.Update]:
    await session.send(prompt)
    updates: list[claude.Update] = []
    async with aclosing(session.updates()) as stream:
        async for update in stream:
            updates.append(update)
            if isinstance(update, TurnEnded):
                break
    return updates


# ---------------------------------------------------------------- where sessions may run


async def test_open_refuses_the_primary_checkout(
    settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    with pytest.raises(ClaudeError, match="isn't a RepoCop worktree"):
        await claude.Session.open(settings, repo, repo.primary_path, factory=fake_claude)
    assert fake_claude.clients == []


async def test_open_refuses_a_folder_that_is_not_a_worktree(
    settings: Settings, repo: Repository, fake_claude: FakeClaudeFactory
) -> None:
    folder = settings.worktrees_root / "sample" / "req-9-not-a-worktree"
    folder.mkdir(parents=True)
    with pytest.raises(ClaudeError, match="isn't a RepoCop worktree"):
        await claude.Session.open(settings, repo, folder, factory=fake_claude)
    assert fake_claude.clients == []


async def test_open_runs_in_the_worktree_with_project_settings_and_no_bypass(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    options = fake_claude.clients[0].options
    assert options.cwd == str(worktree)
    assert options.setting_sources == ["project"]
    assert options.permission_mode == "acceptEdits"
    assert "dangerously-skip-permissions" not in str(options.extra_args)
    assert options.resume is None
    assert fake_claude.clients[0].connected


async def test_open_resumes_a_given_session(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    await claude.Session.open(settings, repo, worktree, resume="session-7", factory=fake_claude)
    assert fake_claude.clients[0].options.resume == "session-7"


# ---------------------------------------------------------------- updates


async def test_a_skill_turn_yields_the_session_visible_activity_and_its_end(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    session = await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    updates = await turn(session, f"/implement {REQUIREMENT}")
    session_id = fake_claude.clients[0].session_id
    assert updates == [
        SessionStarted(session_id, "none"),
        Event("assistant_text", {"text": f"Following /implement for {REQUIREMENT}."}),
        Event("tool_use", {"id": "toolu_1", "name": "Read", "input": {"file_path": REQUIREMENT}}),
        Event(
            "tool_result",
            {"tool_use_id": "toolu_1", "content": "# Req\n\nDo it.\n", "is_error": False},
        ),
        Event("assistant_text", {"text": "Done with /implement."}),
        TurnEnded(ok=True, result="Done with /implement.", error=None),
    ]


async def test_thinking_is_never_surfaced(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    session = await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    updates = await turn(session, f"/implement {REQUIREMENT}")
    assert THINKING not in repr(updates)


async def test_an_unknown_skill_ends_the_turn_with_an_error(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    session = await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    updates = await turn(session, f"/deploy {REQUIREMENT}")
    assert updates[-1] == TurnEnded(
        ok=False, result="Unknown skill: /deploy", error="Unknown skill: /deploy"
    )


async def test_interrupt_ends_the_turn_as_interrupted(
    settings: Settings, repo: Repository, worktree: Path
) -> None:
    slow = FakeClaudeFactory(delay=0.05)
    session = await claude.Session.open(settings, repo, worktree, factory=slow)
    await session.send(f"/implement {REQUIREMENT}")
    updates: list[claude.Update] = []
    async with aclosing(session.updates()) as stream:
        async for update in stream:
            updates.append(update)
            if isinstance(update, SessionStarted):
                await session.interrupt()
            if isinstance(update, TurnEnded):
                break
    assert Event("raw", {"text": "[Request interrupted by user]"}) in updates
    assert updates[-1] == TurnEnded(ok=False, result=None, error="error_during_execution")


async def test_long_text_is_clipped(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    (worktree / "big.txt").write_text("x" * (claude.MAX_EVENT_TEXT + 500))
    session = await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    updates = await turn(session, "/implement big.txt")
    result = next(u for u in updates if isinstance(u, Event) and u.kind == "tool_result")
    assert len(result.payload["content"]) < claude.MAX_EVENT_TEXT + 100
    assert result.payload["content"].endswith("(clipped)")


async def test_open_refuses_another_repositorys_checkout_at_the_worktree_path(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    remote_repo: Path,
    tmp_path: Path,
    fake_claude: FakeClaudeFactory,
) -> None:
    worktree.rename(tmp_path / "moved-away")
    run_git("clone", "-q", "--bare", str(remote_repo), str(tmp_path / "other.git"), cwd=tmp_path)
    run_git("clone", "-q", str(tmp_path / "other.git"), str(worktree), cwd=tmp_path)
    with pytest.raises(ClaudeError, match="isn't a RepoCop worktree"):
        await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    assert fake_claude.clients == []


# ---------------------------------------------------------------- authentication


def with_api_key(settings: Settings) -> Settings:
    return settings.model_copy(update={"anthropic_api_key": SecretStr("sk-ant-configured")})


async def test_sessions_use_the_subscription_even_with_a_key_in_the_environment(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_claude: FakeClaudeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-for-other-tools")
    await claude.Session.open(settings, repo, worktree, factory=fake_claude)
    assert fake_claude.clients[0].options.env["ANTHROPIC_API_KEY"] == ""


async def test_sessions_use_a_configured_api_key(
    settings: Settings, repo: Repository, worktree: Path, fake_claude: FakeClaudeFactory
) -> None:
    session = await claude.Session.open(with_api_key(settings), repo, worktree, factory=fake_claude)
    assert fake_claude.clients[0].options.env["ANTHROPIC_API_KEY"] == "sk-ant-configured"
    assert (await turn(session, f"/implement {REQUIREMENT}"))[-1] == TurnEnded(
        ok=True, result="Done with /implement.", error=None
    )


async def test_a_session_using_an_unexpected_api_key_is_stopped(
    settings: Settings, repo: Repository, worktree: Path
) -> None:
    keyed = FakeClaudeFactory(api_key_source="apiKeyHelper")
    session = await claude.Session.open(settings, repo, worktree, factory=keyed)
    with pytest.raises(ClaudeError, match="API key"):
        await turn(session, f"/implement {REQUIREMENT}")


async def test_a_session_ignoring_the_configured_api_key_is_stopped(
    settings: Settings, repo: Repository, worktree: Path
) -> None:
    unkeyed = FakeClaudeFactory(api_key_source="none")
    session = await claude.Session.open(with_api_key(settings), repo, worktree, factory=unkeyed)
    with pytest.raises(ClaudeError, match="configured API key"):
        await turn(session, f"/implement {REQUIREMENT}")


def test_auth_status_reports_the_subscription(settings: Settings) -> None:
    status = claude.auth_status(settings)
    assert (status.kind, status.plan, status.account, status.problem) == (
        claude.AuthKind.SUBSCRIPTION,
        "max",
        "you@example.invalid",
        None,
    )


def test_auth_status_reports_a_configured_api_key(settings: Settings) -> None:
    status = claude.auth_status(with_api_key(settings))
    assert (status.kind, status.problem) == (claude.AuthKind.API_KEY, None)


def test_auth_status_says_how_to_log_in(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_OUT", "1")
    problem = claude.auth_status(settings).problem
    assert problem is not None and "claude auth login" in problem


def test_auth_status_reports_a_missing_cli(settings: Settings, tmp_path: Path) -> None:
    missing = settings.model_copy(update={"claude_bin": str(tmp_path / "no-claude")})
    problem = claude.auth_status(missing).problem
    assert problem is not None and "isn't installed" in problem


# ---------------------------------------------------------------- session processes


def gone(process: subprocess.Popen[bytes], timeout: float = 5.0) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def test_stop_ends_the_recorded_process(tmp_path: Path) -> None:
    process = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
    ref = claude.process_ref(process.pid)
    assert ref is not None and claude.is_running(ref)
    assert claude.stop(ref)
    assert gone(process)
    assert not claude.is_running(ref)


def test_stop_leaves_a_process_that_is_not_the_recorded_one(tmp_path: Path) -> None:
    process = subprocess.Popen(["sleep", "30"], cwd=tmp_path)
    try:
        assert not claude.stop(claude.ProcessRef(process.pid, "not-its-start-time"))
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()


def test_stop_reports_nothing_for_a_finished_process(tmp_path: Path) -> None:
    process = subprocess.Popen(["cat"], cwd=tmp_path, stdin=subprocess.PIPE)
    ref = claude.process_ref(process.pid)  # it runs until its input closes
    process.communicate()
    assert ref is not None and not claude.stop(ref)


def group_with_a_child(tmp_path: Path) -> tuple[subprocess.Popen[bytes], int]:
    """A process leading a group of its own, and the id of a child in that group."""
    leader = subprocess.Popen(
        ["sh", "-c", "sleep 30 & echo $!; wait"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    assert leader.stdout is not None
    return leader, int(leader.stdout.readline())


def test_stop_with_group_ends_everything_in_the_recorded_processs_group(tmp_path: Path) -> None:
    leader, child = group_with_a_child(tmp_path)
    try:
        ref = claude.process_ref(leader.pid)
        assert ref is not None and claude.stop(ref, group=True)
        assert gone(leader) and process_gone(child)
    finally:
        kill_process(child)


def test_stop_with_group_leaves_a_group_led_by_another_process(tmp_path: Path) -> None:
    leader, child = group_with_a_child(tmp_path)
    try:
        assert not claude.stop(claude.ProcessRef(leader.pid, "not-its-start-time"), group=True)
        assert leader.poll() is None and not process_gone(child, timeout=0.2)
    finally:
        os.killpg(leader.pid, signal.SIGKILL)
        leader.wait()


async def test_open_records_the_session_process_it_started(
    settings: Settings, repo: Repository, worktree: Path
) -> None:
    factory = FakeClaudeFactory(process="exits")
    session = await claude.Session.open(settings, repo, worktree, factory=factory)
    stand_in = factory.clients[0].process
    assert stand_in is not None
    assert session.process is not None and session.process.pid == stand_in.pid
    await session.close()


async def test_close_stops_a_session_process_that_outlives_disconnect(
    settings: Settings, repo: Repository, worktree: Path
) -> None:
    factory = FakeClaudeFactory(process="lingers")
    session = await claude.Session.open(settings, repo, worktree, factory=factory)
    await session.close()
    stand_in = factory.clients[0].process
    assert stand_in is not None and gone(stand_in)


async def test_a_configured_api_key_wins_over_an_inherited_auth_token(
    settings: Settings,
    repo: Repository,
    worktree: Path,
    fake_claude: FakeClaudeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-for-other-tools")
    await claude.Session.open(with_api_key(settings), repo, worktree, factory=fake_claude)
    env = fake_claude.clients[0].options.env
    assert (env["ANTHROPIC_API_KEY"], env["ANTHROPIC_AUTH_TOKEN"]) == ("sk-ant-configured", "")


async def test_a_session_on_another_key_than_the_configured_one_is_stopped(
    settings: Settings, repo: Repository, worktree: Path
) -> None:
    token = FakeClaudeFactory(api_key_source="ANTHROPIC_AUTH_TOKEN")
    session = await claude.Session.open(with_api_key(settings), repo, worktree, factory=token)
    with pytest.raises(ClaudeError, match="configured API key"):
        await turn(session, f"/implement {REQUIREMENT}")


def test_auth_status_reports_a_key_other_than_the_configured_one(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_KEY_SOURCE", "apiKeyHelper")
    problem = claude.auth_status(with_api_key(settings)).problem
    assert problem is not None and "configured key" in problem


def test_auth_status_reports_a_token_taking_over_from_the_configured_key(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_AUTH_METHOD", "oauth_token")
    problem = claude.auth_status(with_api_key(settings)).problem
    assert problem is not None and "configured key" in problem


# ---------------------------------------------------------------- continuing in a terminal


def test_resume_command_runs_in_the_worktree_and_quotes_each_part(settings: Settings) -> None:
    custom = settings.model_copy(update={"claude_bin": "/opt/my claude"})
    command = claude.resume_command(custom, Path("/work/my tree"), "abc-123")
    assert command == "cd '/work/my tree' && '/opt/my claude' --resume abc-123"
