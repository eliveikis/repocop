"""Claude Code, the agent a run uses: whether it's ready, how a run's session is started and
driven, and what its transcript says. The facts about the CLI this relies on are in
`specs/evals.md`, under Claude Code, which `tests/fakes/bin/claude` keeps in step with.

A run is one headless session that takes all of its turns, each sent once the previous turn's
`result` event arrives. It loads only its repository's own settings and instructions, and the
skills, tools and agents Anthropic ships with Claude Code; whatever would prompt for permission
is denied.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from evals.errors import EvalError

PROGRAM = "claude"
CHECK_TIMEOUT_S = 60.0  # how long asking Claude Code its version or sign-in may take
CLOSE_TIMEOUT_S = 60.0  # how long a session may take to end once its last turn has
STOP_GRACE_S = 5.0
# How every run's session starts. Each option is one Claude Code must offer.
SESSION = (
    "-p",
    "--input-format",
    "stream-json",
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
USAGE_LIMIT = "usage limit"  # how a turn the service cut short at a usage limit reads


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
class TurnEnd:
    """How one turn went: its events, and its `result` event unless it timed out or Claude Code
    ended first."""

    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    timed_out: bool = False
    exit_code: int | None = None  # set when Claude Code ended before the turn did


class Session:
    """One headless Claude Code session, which takes a run's turns one after another. Every line
    it writes goes to `transcript` as it comes, beside a line marking where each turn starts."""

    def __init__(
        self, args: Sequence[str], cwd: Path, env: Mapping[str, str], transcript: Path, stderr: Path
    ) -> None:
        self._transcript = transcript.open("a", encoding="utf-8")
        self._stderr = stderr.open("wb")
        self._proc = subprocess.Popen(
            list(args),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,  # its own process group, so stopping it stops its tools too
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, args=(self._proc.stdout,), daemon=True)
        self._reader.start()
        self._turns = 0

    def turn(self, prompt: str, *, timeout: float) -> TurnEnd:
        """Send one turn and wait for its `result`, at most `timeout` seconds. A turn that times
        out stops the session."""
        self._turns += 1
        self._note({"type": "eval", "turn": self._turns, "prompt": prompt})
        end = TurnEnd()
        message = {"type": "user", "message": {"role": "user", "content": prompt}}
        try:
            stdin = self._stdin()
            stdin.write(json.dumps(message) + "\n")
            stdin.flush()
        except OSError:
            end.exit_code = self._proc.wait()
            return end
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                break
            if line is None:
                end.exit_code = self._proc.wait()
                return end
            event = _event(line)
            if event is None:
                continue
            end.events.append(event)
            if event.get("type") == "result":
                end.result = event
                return end
        end.timed_out = True
        self.stop()
        return end

    def close(self) -> None:
        """End the session once its last turn has, and stop it if it doesn't end soon."""
        with contextlib.suppress(OSError):
            self._stdin().close()
        try:
            self._proc.wait(timeout=CLOSE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.stop()
        self._finish()

    def stop(self) -> None:
        """End Claude Code and everything it started: asked first, then forced."""
        for sig, grace in ((signal.SIGTERM, STOP_GRACE_S), (signal.SIGKILL, None)):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self._proc.pid, sig)
            try:
                self._proc.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        self._finish()

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        if self._proc.poll() is None:
            self.stop()
        self._finish()

    def _stdin(self) -> IO[str]:
        if self._proc.stdin is None:  # never: it is a pipe
            raise OSError("the session has no input")
        return self._proc.stdin

    def _read(self, stdout: IO[str] | None) -> None:
        for line in stdout or ():
            self._transcript.write(line if line.endswith("\n") else line + "\n")
            self._transcript.flush()
            self._lines.put(line)
        self._lines.put(None)

    def _note(self, event: dict[str, Any]) -> None:
        self._transcript.write(json.dumps(event) + "\n")
        self._transcript.flush()

    def _finish(self) -> None:
        self._reader.join(timeout=STOP_GRACE_S)
        for file in (self._transcript, self._stderr):
            if not file.closed:
                file.close()


# What a transcript says.


def inits(events: Sequence[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """The `system`/`init` events, one each turn, which say what the session loaded."""
    return (e for e in events if e.get("type") == "system" and e.get("subtype") == "init")


def models(events: Sequence[dict[str, Any]]) -> set[str]:
    """The models the turns ran on."""
    return {e["model"] for e in inits(events) if isinstance(e.get("model"), str)}


def versions(events: Sequence[dict[str, Any]]) -> set[str]:
    """The Claude Code versions the turns ran on."""
    return {v for e in inits(events) if isinstance(v := e.get("claude_code_version"), str)}


def first_shell_command(events: Sequence[dict[str, Any]]) -> str | None:
    """The first shell command the agent ran, or None."""
    for block in _blocks(events, "assistant"):
        if block.get("type") == "tool_use" and block.get("name") == "Bash":
            command = block.get("input", {}).get("command")
            return command if isinstance(command, str) else None
    return None


def reply(end: TurnEnd) -> str | None:
    """The turn's last reply: what its `result` says, or else the agent's last text."""
    if end.result is not None and isinstance(text := end.result.get("result"), str):
        return text
    texts = [b["text"] for b in _blocks(end.events, "assistant") if b.get("type") == "text"]
    return texts[-1] if texts else None


def tool_errors(events: Sequence[dict[str, Any]]) -> int:
    """How many of the agent's tool calls ended in an error."""
    return sum(
        1 for b in _blocks(events, "user") if b.get("type") == "tool_result" and b.get("is_error")
    )


def cut_short_by_service(end: TurnEnd) -> str | None:
    """Why the service, not the agent, ended the turn, as at a usage limit or in an outage, or
    None when it didn't."""
    for event in end.events:
        info = event.get("rate_limit_info") if event.get("type") == "rate_limit_event" else None
        if isinstance(info, dict) and info.get("status") == "rejected":
            return f"the service refused the turn at a usage limit ({info.get('rateLimitType')})"
    result = end.result or {}
    if result.get("api_error_status") is not None:
        return f"the service failed the turn (HTTP {result['api_error_status']})"
    if result.get("is_error") and USAGE_LIMIT in str(result.get("result", "")).lower():
        return "the service refused the turn at a usage limit"
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
