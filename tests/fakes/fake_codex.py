"""The test side of the fake Codex CLI in `tests/fakes/bin/codex`: what it was asked, and how a
review goes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FakeCodex:
    directory: Path  # where the fake keeps its state

    @property
    def records(self) -> list[dict[str, Any]]:
        """Every `codex` call so far: its arguments, working directory and input."""
        log = self.directory / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    @property
    def reviews(self) -> list[dict[str, Any]]:
        """The `codex review` calls so far."""
        return [call for call in self.records if call["args"][:1] == ["review"]]

    def log_out(self) -> None:
        (self.directory / "logged-out").touch()

    def review_says(self, text: str) -> None:
        (self.directory / "review.txt").write_text(text)

    def fail_with(self, error: str) -> None:
        """Make every review fail with this error."""
        (self.directory / "fail").write_text(error)
