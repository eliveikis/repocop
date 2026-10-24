"""A stand-in for the Claude Agent SDK client, so the default test suite never calls Claude.

It produces the SDK's own public message types in the order the real Claude Code produced them
in the ADR-001 check: every turn starts with an `init` system message carrying the session id
and the credential in use (`apiKeySource`: the API key when one is in the environment),
then assistant text and tool use, tool results, and a result message that ends the turn.

A `/skill path` prompt is checked, not carried out: the skill must exist in the worktree's
`.claude/skills/` and the path must be a file there, otherwise the turn ends in an error. Any
other prompt is acknowledged. A prompt sent while a turn runs is answered as the next turn, and
interrupt() ends the current turn the way the real CLI does.
"""

from __future__ import annotations

import asyncio
import itertools
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

MODEL = "fake-model"
THINKING = "(private reasoning RepoCop must never show)"
_session_numbers = itertools.count(1)


class FakeClaude:
    """Implements the part of ClaudeSDKClient that services/claude.py uses."""

    def __init__(
        self,
        options: ClaudeAgentOptions,
        *,
        delay: float = 0.0,
        api_key_source: str | None = None,
        process: str = "none",
    ) -> None:
        self.options = options
        # "none": no OS process; "exits": a stand-in process in the worktree, stopped on
        # disconnect like the real CLI; "lingers": one that outlives disconnect
        self.process_mode = process
        self.process: subprocess.Popen[bytes] | None = None
        uses_key = bool(dict(options.env).get("ANTHROPIC_API_KEY"))
        self.api_key_source = api_key_source or ("ANTHROPIC_API_KEY" if uses_key else "none")
        self.cwd = Path(str(options.cwd))
        self.session_id = options.resume or f"fake-session-{next(_session_numbers)}"
        self.prompts: list[str] = []
        self.delay = delay
        self.connected = False
        self._inbox: asyncio.Queue[str | None] = asyncio.Queue()
        self._interrupted = False

    async def connect(self) -> None:
        self.connected = True
        if self.process_mode != "none":
            self.process = subprocess.Popen(["sleep", "60"], cwd=self.cwd)

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)
        await self._inbox.put(prompt)

    async def interrupt(self) -> None:
        self._interrupted = True

    async def disconnect(self) -> None:
        self.connected = False
        await self._inbox.put(None)
        if self.process is not None and self.process_mode == "exits":
            self.process.terminate()
            self.process.wait()

    async def receive_messages(self) -> AsyncIterator[Any]:
        while (prompt := await self._inbox.get()) is not None:
            self._interrupted = False
            yield SystemMessage(
                "init",
                {
                    "session_id": self.session_id,
                    "cwd": str(self.cwd),
                    "apiKeySource": self.api_key_source,
                },
            )
            for message in self._reply(prompt):
                if self.delay:
                    await asyncio.sleep(self.delay)
                if self._interrupted:
                    yield UserMessage([TextBlock("[Request interrupted by user]")])
                    yield self._result("error_during_execution", None)
                    break
                yield message

    def _reply(self, prompt: str) -> list[Any]:
        if not prompt.startswith("/"):
            return [self._say(f"Noted: {prompt}"), self._result("success", "Noted.")]
        # A skill is given everything after its name, line breaks included: the path is the
        # first line, and whatever follows it rides along.
        skill, _, arguments = prompt[1:].partition(" ")
        argument = arguments.split("\n", 1)[0]
        if not (self.cwd / ".claude" / "skills" / skill / "SKILL.md").is_file():
            return [self._result("error_during_execution", f"Unknown skill: /{skill}")]
        if not argument or not (self.cwd / argument).is_file():
            return [self._result("error_during_execution", f"No such file: {argument!r}")]
        return [
            AssistantMessage([ThinkingBlock(thinking=THINKING, signature="fake")], MODEL),
            self._say(f"Following /{skill} for {argument}."),
            AssistantMessage(
                [ToolUseBlock(id="toolu_1", name="Read", input={"file_path": argument})], MODEL
            ),
            UserMessage(
                [ToolResultBlock(tool_use_id="toolu_1", content=(self.cwd / argument).read_text())]
            ),
            self._say(f"Done with /{skill}."),
            self._result("success", f"Done with /{skill}."),
        ]

    def _say(self, text: str) -> AssistantMessage:
        return AssistantMessage([TextBlock(text)], MODEL, session_id=self.session_id)

    def _result(self, subtype: str, text: str | None) -> ResultMessage:
        return ResultMessage(
            subtype=subtype,
            duration_ms=1,
            duration_api_ms=1,
            is_error=subtype != "success",
            num_turns=1,
            session_id=self.session_id,
            total_cost_usd=0.0,
            result=text,
        )


class FakeClaudeFactory:
    """Makes FakeClaude clients and keeps them, so tests can see what each session was sent."""

    def __init__(
        self, delay: float = 0.0, api_key_source: str | None = None, process: str = "none"
    ) -> None:
        self.delay = delay
        self.api_key_source = api_key_source
        self.process = process
        self.clients: list[FakeClaude] = []

    def __call__(self, options: ClaudeAgentOptions) -> FakeClaude:
        client = FakeClaude(
            options, delay=self.delay, api_key_source=self.api_key_source, process=self.process
        )
        self.clients.append(client)
        return client
