"""Claude Code, the agent a run uses: whether it's ready, how a run's session is started, and
what its transcript says. The facts about the CLI this relies on are in `specs/evals.md`, under
Claude Code, which `tests/fakes/bin/claude` keeps in step with.

A run is one headless session on one prompt. It loads only its repository's own settings and
instructions, and the skills, tools and agents Anthropic ships with Claude Code; whatever would
prompt for permission is denied.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.errors import EvalError

PROGRAM = "claude"
CHECK_TIMEOUT_S = 60.0  # how long asking Claude Code its version or sign-in may take
STOP_GRACE_S = 5.0
# How every run's session starts, with its prompt on standard input. Each option is one Claude
# Code must offer.
SESSION = (
    "-p",
    "--output-format",
    "stream-json",
    "--verbose",
    "--include-hook-events",
    "--setting-sources",
    "project",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--permission-mode",
    "auto",
    "--permission-prompts",
    "none",
)
OPTIONS = (*(arg for arg in SESSION if arg.startswith("--")), "--settings", "--model", "--effort")
SUBSCRIPTION = "claude.ai"  # the sign-in method of a Claude subscription
BUILT_IN_PLUGIN = "@builtin"  # how the source of a plugin that ships with Claude Code ends
USAGE_LIMIT = "usage limit"  # how a run the service cut short at a usage limit reads


def check_ready(env: Mapping[str, str]) -> str:
    """Claude Code's version, once it's sure to be installed, to offer every option a run
    uses, and to be signed in with a subscription in a run's environment `env`. Refused,
    saying which isn't so, otherwise."""
    if shutil.which(PROGRAM, path=env.get("PATH")) is None:
        raise EvalError("Claude Code isn't installed: the eval runs `claude`, which isn't on PATH")
    version = _ask(["--version"], env).split(" ", 1)[0]
    usage = _ask(["--help"], env)
    lacking = [option for option in OPTIONS if option not in usage]
    if lacking:
        raise EvalError(
            f"Claude Code {version} lacks {', '.join(lacking)}, which the eval runs it with: "
            "update it (`claude update`)"
        )
    try:
        status = json.loads(_ask(["auth", "status", "--json"], env, ok_codes=(0, 1)))
    except ValueError:
        status = {}
    if not status.get("loggedIn") or status.get("authMethod") != SUBSCRIPTION:
        raise EvalError(
            "Claude Code isn't signed in with a Claude subscription, as the eval runs it: "
            "sign in with `claude auth login`, which runs share"
        )
    return version


def config_folder(env: Mapping[str, str]) -> Path:
    """The developer's own Claude Code configuration folder, which holds their sign-in."""
    with contextlib.suppress(EvalError, ValueError):
        found = json.loads(_ask(["auth", "status", "--json"], env, ok_codes=(0, 1)))
        if isinstance(folder := found.get("configDirectory"), str):
            return Path(folder)
    return Path(env.get("HOME", "~")).expanduser() / ".claude"


def argv(repo: Path, *, model: str | None, effort: str | None) -> list[str]:
    """How a run's session starts in its repository `repo`.

    A headless session drops a project's permission allow rules in a folder no one has trusted,
    and trusting it would mean writing to the developer's own configuration, so the
    repository's own allow rules are passed as settings of the session.
    """
    args = [PROGRAM, *SESSION]
    allowed = own_settings(repo).get("permissions", {}).get("allow")
    if allowed:
        args += ["--settings", json.dumps({"permissions": {"allow": allowed}})]
    if model:
        args += ["--model", model]
    if effort:
        args += ["--effort", effort]
    return args


def own_settings(repo: Path) -> dict[str, Any]:
    """The repository's own Claude Code settings, or none."""
    path = repo / ".claude" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class SessionEnd:
    """How a run's session went: its events, its `result` event unless it timed out or Claude
    Code ended without one, and Claude Code's exit code unless it timed out."""

    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    timed_out: bool = False
    exit_code: int | None = None


def session(
    args: Sequence[str],
    prompt: str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    transcript: Path,
    stderr: Path,
    timeout: float,
) -> SessionEnd:
    """Run one headless session on `prompt`, given on its standard input, and wait at most
    `timeout` seconds for it to end: one that takes longer is stopped, with everything it
    started. Every line it writes goes to `transcript` as it comes."""
    end = SessionEnd()
    with transcript.open("w", encoding="utf-8") as log, stderr.open("wb") as errors:
        proc = subprocess.Popen(
            list(args),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,  # its own process group, so stopping it stops its tools too
        )
        timer = threading.Timer(timeout, _expire, (proc, end))
        timer.start()
        try:
            if proc.stdin is not None and proc.stdout is not None:  # both pipes, so never None
                with contextlib.suppress(OSError):  # it may end before reading its prompt
                    proc.stdin.write(prompt + "\n")
                    proc.stdin.close()
                for line in proc.stdout:
                    log.write(line)
                    log.flush()
                    if (event := _event(line)) is not None:
                        end.events.append(event)
                        if event.get("type") == "result":
                            end.result = event
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                _stop(proc)
    if not end.timed_out:
        end.exit_code = proc.returncode
    return end


def _expire(proc: subprocess.Popen[str], end: SessionEnd) -> None:
    end.timed_out = True
    _stop(proc)


def _stop(proc: subprocess.Popen[str]) -> None:
    """End Claude Code and everything it started: asked first, then forced."""
    for sig, grace in ((signal.SIGTERM, STOP_GRACE_S), (signal.SIGKILL, None)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, sig)
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


# What a transcript says.


def inits(events: Sequence[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """The `system`/`init` events, which say what the session loaded and its model."""
    return (e for e in events if e.get("type") == "system" and e.get("subtype") == "init")


def models(events: Sequence[dict[str, Any]]) -> set[str]:
    """The models the session ran on."""
    return {e["model"] for e in inits(events) if isinstance(e.get("model"), str)}


def versions(events: Sequence[dict[str, Any]]) -> set[str]:
    """The Claude Code versions the session ran on."""
    return {v for e in inits(events) if isinstance(v := e.get("claude_code_version"), str)}


def first_shell_command(events: Sequence[dict[str, Any]]) -> str | None:
    """The first shell command the agent ran, or None."""
    for block in _blocks(events, "assistant"):
        if block.get("type") == "tool_use" and block.get("name") == "Bash":
            command = block.get("input", {}).get("command")
            return command if isinstance(command, str) else None
    return None


def reply(end: SessionEnd) -> str | None:
    """The agent's last reply: what its `result` says, or else the agent's last text."""
    if end.result is not None and isinstance(text := end.result.get("result"), str):
        return text
    texts = [b["text"] for b in _blocks(end.events, "assistant") if b.get("type") == "text"]
    return texts[-1] if texts else None


def tool_errors(events: Sequence[dict[str, Any]]) -> int:
    """How many of the agent's tool calls ended in an error."""
    return sum(
        1 for b in _blocks(events, "user") if b.get("type") == "tool_result" and b.get("is_error")
    )


def cut_short_by_service(end: SessionEnd) -> str | None:
    """Why the service, not the agent, ended the run, as at a usage limit or in an outage, or
    None when it didn't."""
    for event in end.events:
        info = event.get("rate_limit_info") if event.get("type") == "rate_limit_event" else None
        if isinstance(info, dict) and info.get("status") == "rejected":
            return f"the service refused the run at a usage limit ({info.get('rateLimitType')})"
    result = end.result or {}
    if result.get("api_error_status") is not None:
        return f"the service failed the run (HTTP {result['api_error_status']})"
    if result.get("is_error") and USAGE_LIMIT in str(result.get("result", "")).lower():
        return "the service refused the run at a usage limit"
    return None


@dataclass(frozen=True)
class Own:
    """What the developer's own Claude Code configuration adds, by name: what a run must not
    load."""

    skills: frozenset[str] = frozenset()
    agents: frozenset[str] = frozenset()
    commands: frozenset[str] = frozenset()
    output_styles: frozenset[str] = frozenset()

    @classmethod
    def read(cls, folder: Path) -> Own:
        """The developer's own skills, agents, commands and output styles in their user-level
        configuration `folder`. A skill synced from claude.ai is theirs unless Anthropic made it."""
        skills = {p.name for p in _children(folder / "skills") if p.is_dir() and p.name != "synced"}
        for manifest in (folder / "skills" / "synced").glob("*/manifest.json"):
            with contextlib.suppress(OSError, ValueError, AttributeError, TypeError):
                for skill in json.loads(manifest.read_text(encoding="utf-8")).get("skills", []):
                    if skill.get("creatorType") != "anthropic" and skill.get("name"):
                        skills.add(skill["name"])
        commands = folder / "commands"
        return cls(
            skills=frozenset(skills),
            agents=frozenset(p.stem for p in (folder / "agents").rglob("*.md")),
            commands=frozenset(
                ":".join(p.relative_to(commands).with_suffix("").parts)
                for p in commands.rglob("*.md")
            ),
            output_styles=frozenset(p.stem for p in (folder / "output-styles").rglob("*.md")),
        )


def developers_own(events: Sequence[dict[str, Any]], own: Own, repo: Path) -> list[str]:
    """What of the developer's own the session loaded, by kind and name, sorted: their skills,
    agents, commands, output styles, plugins, MCP servers and hooks. What the repository has
    under the same name is the repository's. Any MCP server is theirs, as is any plugin that
    doesn't ship with Claude Code, and any hook on an event the repository's settings don't
    hook, since hook events don't say which command ran."""
    repository = Own(
        skills=frozenset(p.name for p in _children(repo / ".claude" / "skills")),
        agents=frozenset(p.stem for p in (repo / ".claude" / "agents").rglob("*.md")),
        commands=frozenset(p.stem for p in (repo / ".claude" / "commands").rglob("*.md")),
    )
    hooked = set(own_settings(repo).get("hooks", {}))
    found: set[str] = set()
    for init in inits(events):
        found |= _named(init.get("skills"), own.skills - repository.skills, "skill")
        found |= _named(init.get("agents"), own.agents - repository.agents, "agent")
        found |= _named(init.get("slash_commands"), own.commands - repository.commands, "command")
        found |= _named([init.get("output_style")], own.output_styles, "output style")
        for plugin in init.get("plugins") or []:
            if isinstance(plugin, dict) and not str(plugin.get("source")).endswith(BUILT_IN_PLUGIN):
                found.add(f"plugin {plugin.get('source') or plugin.get('name')}")
        for server in init.get("mcp_servers") or []:
            name = server.get("name") if isinstance(server, dict) else server
            found.add(f"MCP server {name}")
    for event in events:
        started = event.get("type") == "system" and event.get("subtype") == "hook_started"
        if started and (hook := event.get("hook_event")) not in hooked:
            found.add(f"hook on {hook}")
    return sorted(found)


def _named(loaded: object, own: frozenset[str], kind: str) -> set[str]:
    names = loaded if isinstance(loaded, list) else []
    return {f"{kind} {name}" for name in names if isinstance(name, str) and name in own}


def _children(folder: Path) -> list[Path]:
    return list(folder.iterdir()) if folder.is_dir() else []


def _blocks(events: Sequence[dict[str, Any]], kind: str) -> Iterator[dict[str, Any]]:
    for event in events:
        if event.get("type") == kind and event.get("parent_tool_use_id") is None:
            content = event.get("message", {}).get("content")
            yield from (
                (b for b in content if isinstance(b, dict)) if isinstance(content, list) else ()
            )


def _event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _ask(args: list[str], env: Mapping[str, str], ok_codes: tuple[int, ...] = (0,)) -> str:
    try:
        result = subprocess.run(
            [PROGRAM, *args],
            env=dict(env),
            cwd=tempfile.gettempdir(),  # a folder whose settings no one wrote
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvalError(f"`claude {' '.join(args)}` didn't answer: {exc}") from exc
    if result.returncode not in ok_codes:
        raise EvalError(f"`claude {' '.join(args)}` failed: {result.stderr.strip()}")
    return result.stdout
