"""The test side of the fake GitHub CLI in `tests/fakes/bin/gh`: what it was asked, and what it
answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FakeGh:
    directory: Path  # where the fake keeps its state

    @property
    def calls(self) -> list[list[str]]:
        """The arguments of every `gh` call so far, in order."""
        return [call["args"] for call in self.records]

    @property
    def records(self) -> list[dict[str, Any]]:
        """Every `gh` call so far: its arguments, working directory and prompt setting."""
        log = self.directory / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def log_out(self) -> None:
        (self.directory / "logged-out").touch()

    def fail_with(self, stderr: str) -> None:
        """Make every `gh pr` command fail with this message."""
        (self.directory / "fail").write_text(stderr)

    def add_pull_request(self, branch: str, url: str, *, fork: bool = False) -> None:
        """An open pull request that exists on GitHub already, from `branch` of this repository
        or, with `fork`, of a fork's."""
        pulls_file = self.directory / "pulls.json"
        pulls = json.loads(pulls_file.read_text()) if pulls_file.exists() else {}
        pulls[branch] = {"url": url, "fork": fork}
        pulls_file.write_text(json.dumps(pulls))

    def close_pull_requests(self) -> None:
        """Every pull request has been merged or closed on GitHub."""
        (self.directory / "pulls.json").write_text("{}")
