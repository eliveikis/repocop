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
    def calls(self) -> list[list[str]]:
        """The arguments of every `codex` call so far, in order."""
        return [call["args"] for call in self.records]

    @property
    def records(self) -> list[dict[str, Any]]:
        """Every `codex` call so far: its arguments, working directory and input."""
        log = self.directory / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    @property
    def reviews(self) -> list[dict[str, Any]]:
        """The `codex review` calls so far."""
        return [call for call in self.records if call["args"][:1] == ["review"]]

    @property
    def started(self) -> bool:
        """True once a review told to hang is running."""
        return (self.directory / "started").exists()

    def log_out(self) -> None:
        (self.directory / "logged-out").touch()

    def review_says(self, text: str) -> None:
        (self.directory / "review.txt").write_text(text)

    def fail_with(self, error: str) -> None:
        """Make every review fail with this error."""
        (self.directory / "fail").write_text(error)

    def leave_behind(self, name: str) -> None:
        """Make every review write this file into the folder it runs in."""
        (self.directory / "write").write_text(name)

    def hang(self) -> None:
        """Make every review wait until it is stopped."""
        (self.directory / "hang").touch()

    def print_a_long_line(self) -> None:
        """Make every review print a progress line longer than a stream's default limit."""
        (self.directory / "long-line").touch()

    def leave_a_stubborn_child(self) -> None:
        """Make every review first start a child that ignores SIGTERM."""
        (self.directory / "orphan").touch()

    def close_progress_and_wait(self) -> None:
        """Make every review close its progress output, then wait until it is stopped."""
        (self.directory / "close-stderr").touch()

    def hold_output_open(self) -> None:
        """Make every review exit while a child it started holds its standard output open."""
        (self.directory / "hold-stdout").touch()

    @property
    def child_pid(self) -> int | None:
        """The process id of the child a review started, once it runs."""
        found = self.directory / "child.pid"
        text = found.read_text().strip() if found.exists() else ""
        return int(text) if text else None
