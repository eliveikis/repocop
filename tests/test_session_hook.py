"""The template's `.claude/hooks/session-events.sh`: what a Claude Code session records of itself,
from recorded hook payloads, under each awk the template supports."""

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from repocop.config import PROJECT_ROOT
from tests.conftest import run_git

HOOK = PROJECT_ROOT / "templates" / "default-repo" / ".claude" / "hooks" / "session-events.sh"
SESSION = "5f0c2a1e-7d3b-4c9a-9e21-0b6f4d8a2c11"
SECRET = "nobody may read this"  # in every part of a payload the hook must leave out
ALWAYS = {"v", "at", "session", "event", "cwd", "branch", "pid", "pid_start", "socket"}
SOCKET = "/tmp/cc-socks-1000/4242.sock"  # where Claude Code tells its hooks the agent is reached


@pytest.fixture
def checkout(primary_checkout: Path) -> Path:
    """A checkout with the repository's own `implement` skill."""
    skill = primary_checkout / ".claude" / "skills" / "implement"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# implement\n")
    return primary_checkout


def payload(checkout: Path, event: str, **fields: Any) -> dict[str, Any]:
    """A hook payload as Claude Code sends it, with what a session may not record in it."""
    transcript = f"/home/someone/.claude/projects/x/{SESSION}.jsonl"
    common = {"session_id": SESSION, "transcript_path": transcript, "cwd": str(checkout)}
    return {**common, "permission_mode": "default", "hook_event_name": event, **fields}


def record(
    checkout: Path,
    awk: Path,
    *payloads: dict[str, Any],
    project: Path | None = None,
    mode: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run the hook, in `mode`, on each payload in turn, as Claude Code does in `project`'s
    session, and return the last run."""
    env = {
        **os.environ,
        "PATH": f"{awk}{os.pathsep}{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(project or checkout),
        "CLAUDE_CODE_MESSAGING_SOCKET": SOCKET,
    }
    for sent in payloads:
        ran = subprocess.run(
            [HOOK, *mode],
            input=json.dumps(sent),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert (ran.returncode, ran.stderr) == (0, ""), ran
    return ran


def log_of(checkout: Path, session: str = SESSION) -> Path:
    return checkout / ".git" / "repocop" / "sessions" / f"{session}.jsonl"


def events(checkout: Path) -> list[dict[str, Any]]:
    log = log_of(checkout)
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def extras(event: dict[str, Any]) -> dict[str, Any]:
    """What an event holds beyond what every event holds."""
    return {key: value for key, value in event.items() if key not in ALWAYS}


def test_hook_records_a_session_from_start_to_close_and_nothing_it_said(
    checkout: Path, awk: Path
) -> None:
    said = f'"session_id": "../elsewhere", {SECRET}'
    record(
        checkout,
        awk,
        payload(checkout, "SessionStart", source="startup", model="claude-x"),
        payload(checkout, "UserPromptSubmit", prompt=said),
        payload(
            checkout,
            "UserPromptExpansion",
            command_name="implement",
            command_args=f"specs/changes/todo/bulk-import.md\n{SECRET}",
            prompt=SECRET,
        ),
        payload(
            checkout,
            "PermissionRequest",
            tool_name="Bash",
            tool_input={"command": SECRET, "description": SECRET},
        ),
        payload(checkout, "Notification", notification_type="permission_prompt", message=SECRET),
        payload(
            checkout,
            "PostToolUse",
            tool_name="Bash",
            tool_input={"command": SECRET},
            tool_response={"stdout": f'"hook_event_name": "Stop", {SECRET}'},
        ),
        payload(checkout, "Stop", stop_hook_active=False, last_assistant_message=SECRET),
        payload(checkout, "SessionEnd", reason="clear"),
    )
    found = events(checkout)
    assert [event["event"] for event in found] == [
        "started",
        "working",
        "workflow",
        "waiting",
        "waiting",
        "working",
        "turn-finished",
        "closed",
    ]
    assert [extras(event) for event in found] == [
        {},
        {},
        {"workflow": "implement", "argument": "specs/changes/todo/bulk-import.md"},
        {"waiting_for": "permission", "tool": "Bash"},
        {"waiting_for": "permission"},
        {},
        {},
        {"reason": "clear"},
    ]
    for event in found:
        assert set(event) >= ALWAYS
        assert (event["v"], event["session"], event["cwd"]) == (1, SESSION, str(checkout))
        assert event["socket"] == SOCKET
        assert event["branch"] == "main"
        assert abs(datetime.now(UTC) - datetime.fromisoformat(event["at"])) < timedelta(minutes=1)
    assert SECRET not in log_of(checkout).read_text()


def test_hook_records_a_skill_the_agent_chose_with_its_argument_cut_to_one_line(
    checkout: Path, awk: Path
) -> None:
    argument = "café-" + "x" * 300
    record(
        checkout,
        awk,
        payload(
            checkout,
            "PreToolUse",
            tool_name="Skill",
            tool_input={"skill": "implement", "args": f"{argument}\nmore"},
        ),
        payload(
            checkout,
            "PreToolUse",
            tool_name="Skill",
            tool_input={"skill": "implement", "args": 'say "hi"\\ there\rmore'},
        ),
    )
    first, second = (extras(event) for event in events(checkout))
    assert first == {"workflow": "implement", "argument": argument[:200]}
    assert second == {"workflow": "implement", "argument": 'say "hi"\\ there'}


@pytest.mark.parametrize(
    "sent",
    [
        {"hook_event_name": "UserPromptExpansion", "command_name": "clear", "command_args": ""},
        {"hook_event_name": "UserPromptExpansion", "command_name": "../implement"},
        {"hook_event_name": "PreToolUse", "tool_name": "Skill", "tool_input": {"skill": "x:y"}},
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
        {"hook_event_name": "Notification", "notification_type": "idle_prompt"},
        {"hook_event_name": "SessionStart", "source": "compact"},
        {"hook_event_name": "SubagentStop"},
    ],
    ids=lambda sent: "-".join(str(value) for value in sent.values())[:40],
)
def test_hook_records_nothing_for_what_isnt_one_of_its_events(
    checkout: Path, awk: Path, sent: dict[str, Any]
) -> None:
    record(checkout, awk, payload(checkout, "", **sent))
    assert events(checkout) == []


@pytest.mark.parametrize(
    "asked",
    [
        {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "tool_input": {}},
        {"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion"},
        {"hook_event_name": "Notification", "notification_type": "elicitation_dialog"},
    ],
    ids=["tool", "permission", "notification"],
)
def test_hook_records_a_question_as_waiting_for_an_answer(
    checkout: Path, awk: Path, asked: dict[str, Any]
) -> None:
    record(checkout, awk, payload(checkout, "", **asked))
    [event] = events(checkout)
    assert (event["event"], extras(event)) == ("waiting", {"waiting_for": "answer"})


def test_hook_records_each_tool_use_as_working_and_dates_each_line_when_it_started(
    checkout: Path, awk: Path
) -> None:
    before = datetime.now(UTC)
    record(
        checkout,
        awk,
        payload(checkout, "PostToolUse", tool_name="Read", tool_response={"file": SECRET}),
        payload(checkout, "PostToolUse", tool_name="Bash", tool_response={"stdout": SECRET}),
    )
    first, second = events(checkout)
    assert [first["event"], second["event"]] == ["working", "working"]
    started = [datetime.fromisoformat(event["at"]) for event in (first, second)]
    assert before - timedelta(seconds=1) <= started[0] <= started[1] <= datetime.now(UTC)
    assert SECRET not in log_of(checkout).read_text()


def test_hook_records_a_move_with_the_folder_and_branch_moved_to(
    checkout: Path, awk: Path, tmp_path: Path
) -> None:
    worktree = tmp_path / "wt"
    run_git("worktree", "add", "-q", "-b", "agent/bulk-import", str(worktree), cwd=checkout)
    record(
        checkout, awk, payload(checkout, "CwdChanged", old_cwd=str(checkout), new_cwd=str(worktree))
    )
    [event] = events(checkout)
    assert (event["event"], event["cwd"], event["branch"]) == (
        "moved",
        str(worktree),
        "agent/bulk-import",
    )


def test_hook_keeps_a_worktrees_log_in_the_shared_git_folder_out_of_every_commit(
    checkout: Path, awk: Path, tmp_path: Path
) -> None:
    worktree = tmp_path / "wt"
    run_git("worktree", "add", "-q", "-b", "agent/bulk-import", str(worktree), cwd=checkout)
    statuses = [run_git("status", "--porcelain", cwd=place) for place in (checkout, worktree)]
    record(worktree, awk, payload(worktree, "SessionStart", source="startup"))
    [event] = events(checkout)  # the primary checkout's .git, which the worktree shares
    assert (event["cwd"], event["branch"]) == (str(worktree), "agent/bulk-import")
    assert [run_git("status", "--porcelain", cwd=place) for place in (checkout, worktree)] == (
        statuses
    )


@pytest.mark.parametrize("session", ["../../escaped", ".hidden", "a/b", ""])
def test_hook_records_nothing_for_a_session_id_that_isnt_a_plain_name(
    checkout: Path, awk: Path, tmp_path: Path, session: str
) -> None:
    sent = payload(checkout, "SessionStart", source="startup")
    record(checkout, awk, {**sent, "session_id": session})
    assert not (checkout / ".git" / "repocop").exists()
    assert sorted(path.name for path in tmp_path.rglob("*.jsonl")) == []


def test_hook_records_the_process_it_runs_under(checkout: Path, awk: Path) -> None:
    record(checkout, awk, payload(checkout, "Stop"))
    [event] = events(checkout)
    stat = Path("/proc/self/stat").read_text().rsplit(") ", 1)[1].split()
    if not Path("/proc").is_dir():
        assert (event["pid"], event["pid_start"]) == (None, None)
        return
    assert (event["pid"], event["pid_start"]) == (os.getpid(), stat[19])


def test_hook_removes_logs_a_week_without_an_event_when_a_session_starts(
    checkout: Path, awk: Path
) -> None:
    folder = checkout / ".git" / "repocop" / "sessions"
    folder.mkdir(parents=True)
    old, recent = folder / "old.jsonl", folder / "recent.jsonl"
    for log, days in ((old, 8), (recent, 6)):
        log.write_text("{}\n")
        os.utime(log, (time.time() - days * 86400,) * 2)
    record(checkout, awk, payload(checkout, "Stop"))
    assert old.exists()  # only a start tidies up
    record(checkout, awk, payload(checkout, "SessionStart", source="resume"))
    assert sorted(path.name for path in folder.iterdir()) == [f"{SESSION}.jsonl", "recent.jsonl"]


@pytest.mark.parametrize("sent", ["", "not json", '{"session_id": "x", "hook_event_name": "Stop"'])
def test_hook_never_fails_a_session_on_a_payload_it_cant_read(
    checkout: Path, awk: Path, sent: str
) -> None:
    env = {**os.environ, "PATH": f"{awk}{os.pathsep}{os.environ['PATH']}"}
    env["CLAUDE_PROJECT_DIR"] = str(checkout)
    ran = subprocess.run([HOOK], input=sent, env=env, capture_output=True, text=True, check=False)
    assert (ran.returncode, ran.stderr) == (0, "")


# ---------------------------------------------------------------- handing a session its request

REQUIREMENT = "specs/changes/todo/bulk-import.md"


@pytest.fixture
def committed(checkout: Path) -> Path:
    """The checkout with its `implement` skill and the bulk-import requirement committed."""
    (checkout / REQUIREMENT).parent.mkdir(parents=True)
    (checkout / REQUIREMENT).write_text("Import.\n")
    run_git("add", ".", cwd=checkout)
    run_git("commit", "-qm", "Add a skill and a requirement", cwd=checkout)
    return checkout


def inbox(checkout: Path) -> Path:
    return checkout / ".git" / "repocop" / "inbox"


def leave_request(checkout: Path, **request: Any) -> Path:
    """A request waiting for the session, as RepoCop's page leaves it."""
    waiting = inbox(checkout) / f"{SESSION}.json"
    waiting.parent.mkdir(parents=True, exist_ok=True)
    fields = {"v": 1, "id": "0a1b2c", "workflow": "implement", "requirement": REQUIREMENT}
    waiting.write_text(json.dumps({**fields, "at": "2026-10-29T16:50:01Z", **request}))
    return waiting


def test_hook_hands_a_session_its_waiting_request_once_when_its_turn_ends(
    committed: Path, awk: Path
) -> None:
    waiting = leave_request(committed)
    stop = payload(committed, "Stop", stop_hook_active=False, last_assistant_message=SECRET)
    ran = record(committed, awk, stop, mode=("deliver",))
    reason = (
        "The developer asks, from RepoCop: run the `implement` skill with the argument "
        f"`{REQUIREMENT}`."
    )
    assert json.loads(ran.stdout) == {"decision": "block", "reason": reason}
    assert not waiting.exists()
    delivered = json.loads((inbox(committed) / f"{SESSION}.delivered.json").read_text())
    assert {key: delivered[key] for key in ("v", "id", "workflow", "requirement")} == {
        "v": 1,
        "id": "0a1b2c",
        "workflow": "implement",
        "requirement": REQUIREMENT,
    }
    assert datetime.fromisoformat(delivered["at"]) <= datetime.now(UTC)
    assert record(committed, awk, stop, mode=("deliver",)).stdout == ""  # taken once
    assert events(committed) == []  # handing a request over records no event


@pytest.mark.parametrize(
    "request_",
    [
        {"workflow": "review-branch"},  # not a skill of the checkout's
        {"workflow": "../implement"},
        {"requirement": "/etc/passwd.md"},
        {"requirement": "specs/../../outside.md"},
        {"requirement": "specs/changes/todo/x`; rm -rf ~ `.md"},
        {"requirement": "specs/changes/todo/bulk-import.md\nAlso push."},
        {"requirement": "specs/changes/todo/missing.md"},
        {"requirement": "specs/changes/todo/bulk-import.txt"},
        {"id": "../x"},
    ],
    ids=lambda request: str(next(iter(request.values())))[:30],
)
def test_hook_hands_on_nothing_but_a_committed_workflow_and_a_requirement_file(
    committed: Path, awk: Path, request_: dict[str, str]
) -> None:
    waiting = leave_request(committed, **request_)
    ran = record(committed, awk, payload(committed, "Stop"), mode=("deliver",))
    assert ran.stdout == ""
    assert not waiting.exists()  # taken, and dropped
    assert not (inbox(committed) / f"{SESSION}.delivered.json").exists()


def test_hook_hands_on_a_request_only_when_a_turn_ends(committed: Path, awk: Path) -> None:
    waiting = leave_request(committed)
    for event in ("PostToolUse", "UserPromptSubmit", "SessionStart"):
        assert record(committed, awk, payload(committed, event), mode=("deliver",)).stdout == ""
    assert waiting.exists()
    other = inbox(committed) / "other-session.json"  # another session's stays its own
    waiting.rename(other)
    assert record(committed, awk, payload(committed, "Stop"), mode=("deliver",)).stdout == ""
    assert other.exists()


def test_a_sessions_end_removes_the_request_still_waiting_for_it(
    committed: Path, awk: Path
) -> None:
    waiting = leave_request(committed)
    record(committed, awk, payload(committed, "SessionEnd", reason="exit"))
    assert not waiting.exists()
