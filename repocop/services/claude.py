"""Claude Code: the only module that talks to it (invariant 2), through the Python Agent SDK.

A session runs in one of a repository's RepoCop-owned worktrees and nowhere else, which is
checked before every launch. It loads the worktree's project settings (CLAUDE.md, rules, skills,
allowlist) and runs with `acceptEdits`, never bypassing permissions (ADR-008). It authenticates
with the host's Claude Code subscription unless an API key is configured, and stops a session
that reports any other credential (ADR-018). It turns the SDK's messages into RepoCop's
updates: the session id, the user-visible events for `task_events` (text, tool use, tool
results; never thinking), and the end of each turn. A prompt sent while a turn runs is queued by
Claude Code and answered as the next turn. Details: "Claude Code integration" in
`specs/architecture.md`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import worktrees
from repocop.services.repositories import Repository

MAX_EVENT_TEXT = 20_000
CLIPPED = "\n… (clipped)"
AUTH_STATUS_TIMEOUT_S = 20.0
STOP_GRACE_S = 5.0
PROC = Path("/proc")  # process lookup is Linux-only; elsewhere session processes aren't found
# Environment variables that make Claude Code use a key instead of the subscription login.
KEY_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Where the configured key is passed, and so the apiKeySource Claude Code reports for it.
CONFIGURED_KEY_SOURCE = "ANTHROPIC_API_KEY"


class ClaudeError(RepoCopError):
    """A Claude session can't be launched where or how it was asked."""


class Client(Protocol):
    """The part of the SDK's ClaudeSDKClient RepoCop uses."""

    async def connect(self) -> None: ...

    async def query(self, prompt: str) -> None: ...

    def receive_messages(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], Client]


def sdk_client(options: ClaudeAgentOptions) -> Client:
    """The real client: the SDK driving the Claude Code CLI."""
    return ClaudeSDKClient(options=options)


class AuthKind(StrEnum):
    SUBSCRIPTION = "subscription"  # the host's Claude Code login (the default)
    API_KEY = "api_key"  # `anthropic_api_key` from RepoCop's configuration


@dataclass(frozen=True)
class AuthStatus:
    kind: AuthKind  # what RepoCop is configured to use
    plan: str | None  # the subscription type, e.g. "max"
    account: str | None
    problem: str | None  # why sessions would fail or use another credential; None when fine


@dataclass(frozen=True)
class ProcessRef:
    """One OS process, by id and start time, so a reused id is never mistaken for it."""

    pid: int
    start: str


def process_ref(pid: int) -> ProcessRef | None:
    """The process with this id, if it's running."""
    start = _start_time(pid)
    return ProcessRef(pid, start) if start is not None else None


def is_running(ref: ProcessRef) -> bool:
    """True while the recorded process runs (not once it has exited, even if not yet reaped)."""
    return _start_time(ref.pid) == ref.start


def stop(ref: ProcessRef, grace: float = STOP_GRACE_S, *, group: bool = False) -> bool:
    """Stop the recorded process if it still runs: SIGTERM, then SIGKILL. True if it was running.

    With `group`, the process leads a process group of its own, and each signal goes to the whole
    group.
    """
    if not is_running(ref):
        return False
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, grace)):
        with contextlib.suppress(ProcessLookupError):
            (os.killpg if group else os.kill)(ref.pid, sig)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not is_running(ref):
                return True
            time.sleep(0.05)
    return True


def session_process(worktree: Path) -> ProcessRef | None:
    """The newest process this running RepoCop started with `worktree` as its working directory."""
    if not PROC.is_dir():
        return None
    found = []
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = _stat_fields(entry.name)
            cwd = (entry / "cwd").readlink()
        except (OSError, ValueError):
            continue
        if fields is not None and int(fields[1]) == os.getpid() and cwd == worktree.resolve():
            found.append(ProcessRef(int(entry.name), fields[19]))
    return max(found, key=lambda ref: int(ref.start), default=None)


@dataclass(frozen=True)
class SessionStarted:
    session_id: str
    api_key_source: str | None = None  # "none" when the subscription login is in use


@dataclass(frozen=True)
class Event:
    kind: str  # a task_events kind
    payload: dict[str, Any]


@dataclass(frozen=True)
class TurnEnded:
    ok: bool
    result: str | None
    error: str | None


Update = SessionStarted | Event | TurnEnded


def auth_kind(settings: Settings) -> AuthKind:
    return AuthKind.API_KEY if settings.anthropic_api_key is not None else AuthKind.SUBSCRIPTION


def session_env(settings: Settings) -> dict[str, str]:
    """Credentials for Claude Code: the configured API key, or none at all.

    Every key variable is blanked first, so neither a key nor a token that happens to be in the
    RepoCop's own environment can take over: the subscription login is used, or the key.
    """
    env = dict.fromkeys(KEY_VARIABLES, "")
    if settings.anthropic_api_key is not None:
        env[CONFIGURED_KEY_SOURCE] = settings.anthropic_api_key.get_secret_value()
    return env


def auth_status(settings: Settings) -> AuthStatus:
    """What Claude sessions would authenticate with, from `claude auth status`."""
    kind = auth_kind(settings)
    cli = shutil.which(settings.claude_bin)
    if cli is None:
        return AuthStatus(kind, None, None, f"Claude Code ({settings.claude_bin}) isn't installed")
    workdir = settings.database_path.parent
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [cli, "auth", "status", "--json"],
            cwd=workdir,
            env={**os.environ, **session_env(settings)},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=AUTH_STATUS_TIMEOUT_S,
            check=False,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return AuthStatus(kind, None, None, f"couldn't read Claude Code's login status: {exc}")
    source, method = data.get("apiKeySource"), data.get("authMethod")
    if kind is AuthKind.API_KEY:
        # A token (authMethod oauth_token) takes over even while the key is reported as set.
        uses_key = source == CONFIGURED_KEY_SOURCE and method != "oauth_token"
        problem = None if uses_key else "Claude Code isn't using the configured key"
        return AuthStatus(kind, None, None, problem)
    plan, account = data.get("subscriptionType"), data.get("email")
    if _uses_api_key(source):
        problem = f"Claude Code is set to use an API key ({source}), not your subscription"
    elif not data.get("loggedIn"):
        problem = "Claude Code isn't logged in: run `claude auth login`"
    elif method != "claude.ai":
        problem = f"Claude Code is logged in with {method}, not a Claude subscription"
    else:
        problem = None
    return AuthStatus(kind, plan, account, problem)


def options_for(settings: Settings, worktree: Path, resume: str | None) -> ClaudeAgentOptions:
    """The CLI from `claude_bin` (else the SDK's bundled one), in the worktree, project settings."""
    return ClaudeAgentOptions(
        cwd=str(worktree),
        cli_path=shutil.which(settings.claude_bin),
        setting_sources=["project"],
        permission_mode="acceptEdits",
        resume=resume,
        env=session_env(settings),
    )


def resume_command(settings: Settings, worktree: Path, session_id: str) -> str:
    """A command line for a person to paste into a terminal, continuing a session in its worktree.

    Claude Code looks sessions up by the folder they ran in, so it changes to the worktree first.
    Each part is shell-quoted. It is display text: RepoCop never runs it.
    """
    resume = shlex.join([settings.claude_bin, "--resume", session_id])
    return f"cd {shlex.quote(str(worktree))} && {resume}"


class Session:
    """One Claude Code session in a task's worktree."""

    def __init__(
        self,
        client: Client,
        auth: AuthKind = AuthKind.SUBSCRIPTION,
        process: ProcessRef | None = None,
    ) -> None:
        self._client = client
        self._auth = auth
        self.process = process  # the Claude Code process, when the OS lets us find it

    @classmethod
    async def open(
        cls,
        settings: Settings,
        repository: Repository,
        worktree: Path,
        *,
        resume: str | None = None,
        factory: ClientFactory = sdk_client,
    ) -> Session:
        """Connect a session in `worktree`, refused unless it's one of the repo's worktrees."""
        if not worktrees.is_worktree(repository, settings, worktree):
            raise ClaudeError(
                f"{worktree} isn't a RepoCop worktree of {repository.name}, so Claude won't "
                "run there"
            )
        client = factory(options_for(settings, worktree, resume))
        await client.connect()
        return cls(client, auth_kind(settings), session_process(worktree))

    async def send(self, prompt: str) -> None:
        await self._client.query(prompt)

    async def updates(self) -> AsyncGenerator[Update]:
        """The session's updates. Stops with ClaudeError if it uses another credential."""
        async for message in self._client.receive_messages():
            for update in _updates(message):
                if isinstance(update, SessionStarted):
                    self._check_credential(update.api_key_source)
                yield update

    def _check_credential(self, source: str | None) -> None:
        if self._auth is AuthKind.SUBSCRIPTION and _uses_api_key(source):
            raise ClaudeError(
                f"Claude Code is using an API key ({source}), not your subscription, so the "
                "session was stopped"
            )
        if self._auth is AuthKind.API_KEY and source != CONFIGURED_KEY_SOURCE:
            raise ClaudeError(
                f"Claude Code isn't using the configured API key (it reports {source!r}), so the "
                "session was stopped"
            )

    async def interrupt(self) -> None:
        await self._client.interrupt()

    async def close(self) -> None:
        """Disconnect, and stop the Claude Code process if it outlives that."""
        try:
            await self._client.disconnect()
        finally:
            if self.process is not None and is_running(self.process):
                await asyncio.to_thread(stop, self.process)


def _updates(message: object) -> list[Update]:
    match message:
        case SystemMessage(subtype="init", data=data) if data.get("session_id"):
            return [SessionStarted(str(data["session_id"]), data.get("apiKeySource"))]
        case AssistantMessage(content=blocks):
            return [event for block in blocks if (event := _assistant_event(block))]
        case UserMessage(content=str() as text):
            return [Event("raw", {"text": _clip(text)})]
        case UserMessage(content=blocks):
            return [event for block in blocks if (event := _user_event(block))]
        case ResultMessage():
            error = None
            if message.is_error:
                error = message.result or ", ".join(message.errors or []) or message.subtype
            return [TurnEnded(ok=not message.is_error, result=message.result, error=error)]
    return []


def _assistant_event(block: object) -> Event | None:
    match block:
        case TextBlock(text=text):
            return Event("assistant_text", {"text": _clip(text)})
        case ToolUseBlock(id=tool_id, name=name, input=tool_input):
            return Event("tool_use", {"id": tool_id, "name": name, "input": tool_input})
    return None  # thinking and server-side blocks aren't shown


def _user_event(block: object) -> Event | None:
    match block:
        case ToolResultBlock(tool_use_id=tool_id, content=content, is_error=is_error):
            payload = {
                "tool_use_id": tool_id,
                "content": _clip(_text(content)),
                "is_error": bool(is_error),
            }
            return Event("tool_result", payload)
        case TextBlock(text=text):
            return Event("raw", {"text": _clip(text)})
    return None


def _start_time(pid: int) -> str | None:
    fields = _stat_fields(str(pid))
    if fields is None or fields[0] == "Z":  # gone, or exited and waiting to be reaped
        return None
    return fields[19]


def _stat_fields(pid: str) -> list[str] | None:
    """The fields of /proc/<pid>/stat after the command name: state, ppid, … starttime (19)."""
    try:
        stat = (PROC / pid / "stat").read_text()
    except OSError:
        return None
    return stat[stat.rindex(")") + 2 :].split()


def _uses_api_key(source: object) -> bool:
    return bool(source) and source != "none"


def _text(content: str | list[dict[str, Any]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(str(item.get("text", "")) for item in content if item.get("type") == "text")


def _clip(text: str) -> str:
    return text if len(text) <= MAX_EVENT_TEXT else text[:MAX_EVENT_TEXT] + CLIPPED
