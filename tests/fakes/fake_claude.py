"""The test side of the fake Claude Code CLI in `tests/fakes/bin/claude`: what it was asked, and
how its sessions go."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FakeClaude:
    directory: Path  # where the fake keeps its state: $HOME/.fake-claude

    def plan(self, *sessions: dict[str, Any]) -> None:
        """How each session goes, in order; the last again once they run out."""
        lines = "".join(json.dumps(session) + "\n" for session in sessions)
        (self.directory / "plans.jsonl").write_text(lines)

    def lack(self, option: str) -> None:
        """Make `--help` leave out an option, as an older Claude Code would."""
        (self.directory / "lacks").write_text(option)

    def answer_auth(self, status: dict[str, Any]) -> None:
        """What `auth status --json` says."""
        (self.directory / "auth.json").write_text(json.dumps(status))

    @property
    def calls(self) -> list[dict[str, Any]]:
        """Every `claude` call so far: its arguments, working directory, environment and input."""
        log = self.directory / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    @property
    def sessions(self) -> list[dict[str, Any]]:
        """The headless sessions so far."""
        return [call for call in self.calls if "-p" in call["args"]]
