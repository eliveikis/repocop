"""Codex: the only module that runs `codex`, OpenAI's coding agent, and it runs one thing, its
own review of a branch (ADR-025).

`codex review --base=<ref>` runs in one of a repository's RepoCop-owned worktrees and
nowhere else, which is checked before every launch. It is an argv list with its input closed and
a time limit, in a process group of its own, so stopping the group stops everything it started.
Codex's read-only sandbox is asked for by name, so a host's Codex settings can't loosen it, and no
option that bypasses it is ever passed. The model and the reasoning effort are RepoCop's
settings, when it has them, and Codex's own otherwise.

`codex` is found on `PATH` and uses the login `codex login` stored: RepoCop holds no
credential for it. Its progress arrives on standard error and the review alone on standard
output. Details: "Branch review" in `specs/architecture.md`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.services import worktrees
from repocop.services.repositories import Repository

CODEX = "codex"
NAME = "Codex"  # who a review is by, on the pages
WORKFLOW = "Codex review"  # a review task's workflow: not a name a skill can have
STATUS_TIMEOUT_S = 20.0
REVIEW_TIMEOUT_S = 1800.0
STOP_GRACE_S = 5.0
FLUSH_S = 1.0  # output lines that arrive within this long of each other are one update
MAX_LINES = 200  # and so are at most this many lines
MAX_OUTPUT_TEXT = 20_000
CLIPPED = "\n… (clipped)"
LEFT_OUT = "… (a line too long to show was left out)\n"
# Asked for on every review, whatever the host's own Codex configuration says.
READ_ONLY = ("-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"')


class CodexError(RepoCopError):
    """Codex can't be run where or how it was asked."""


@dataclass(frozen=True)
class Output:
    """What Codex printed while it worked."""

    text: str


@dataclass(frozen=True)
class Finished:
    """How a review ended: with the review Codex wrote, or else with why there is none."""

    review: str | None
    error: str | None


def check_ready(cwd: Path) -> None:
    """Refuse unless `codex` is installed and signed in."""
    try:
        result = subprocess.run(
            [_binary(), "login", "status"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=STATUS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexError(f"couldn't read Codex's sign-in status: {exc}") from exc
    if result.returncode != 0:
        raise CodexError("Codex isn't signed in: run `codex login`")


class Review:
    """One run of Codex's review, in a worktree."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        output: asyncio.StreamReader,
        progress: asyncio.StreamReader,
    ) -> None:
        self._proc = proc
        self._output = output  # standard output: the review, and nothing else
        self._progress = progress  # standard error: what Codex does on the way

    @classmethod
    async def start(
        cls, settings: Settings, repository: Repository, worktree: Path, *, base: str
    ) -> Review:
        """Start a review of `worktree`'s changes against `base`, a branch or other ref.

        Refused unless `worktree` is one of the repository's RepoCop worktrees.
        """
        if not worktrees.is_worktree(repository, settings, worktree):
            raise CodexError(
                f"{worktree} isn't a RepoCop worktree of {repository.name}, so Codex won't "
                "run there"
            )
        args = ["review", f"--base={base}", *READ_ONLY]
        if settings.review_model is not None:
            args += ["-c", f"review_model={json.dumps(settings.review_model)}"]
        if settings.review_effort is not None:
            args += ["-c", f"model_reasoning_effort={json.dumps(settings.review_effort)}"]
        proc = await asyncio.create_subprocess_exec(
            _binary(),
            *args,
            cwd=worktree,
            env={**os.environ, "NO_COLOR": "1"},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # its own process group, so stopping it stops what it runs
        )
        if proc.stdout is None or proc.stderr is None:
            raise CodexError("codex started without its output, so its review can't be read")
        return cls(proc, proc.stdout, proc.stderr)

    @property
    def pid(self) -> int:
        return self._proc.pid

    async def updates(self) -> AsyncGenerator[Output | Finished]:
        """Codex's output as it arrives, then how the review ended. A review that hasn't ended,
        exited and closed its output within `REVIEW_TIMEOUT_S` is stopped."""
        review = asyncio.ensure_future(self._output.read())
        deadline = asyncio.get_running_loop().time() + REVIEW_TIMEOUT_S
        last_lines: deque[str] = deque(maxlen=20)
        try:
            async for lines in _batches(self._progress, deadline):
                last_lines.extend(lines)
                yield Output(_clip("".join(lines).rstrip("\n")))
            code = await asyncio.wait_for(self._proc.wait(), timeout=_left(deadline))
            text = (await asyncio.wait_for(review, timeout=_left(deadline))).decode(
                "utf-8", errors="replace"
            )
            text = text.strip()
        except TimeoutError:
            await self.stop()
            yield Finished(None, f"codex review timed out after {REVIEW_TIMEOUT_S:g}s")
            return
        finally:
            review.cancel()
        if code != 0:
            yield Finished(None, _error(last_lines, code))
        elif not text:
            yield Finished(None, "codex review ended without a review")
        else:
            yield Finished(text, None)

    async def stop(self) -> None:
        """End the review and everything it started that still runs: SIGTERM, then SIGKILL, to
        its whole process group, so a command Codex ran is stopped even once Codex has exited."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not self._group_runs():
                return
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self._proc.pid, sig)
            await self._until_stopped(STOP_GRACE_S)

    def _group_runs(self) -> bool:
        """Whether any process in the review's group is still there."""
        try:
            os.killpg(self._proc.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    async def _until_stopped(self, grace: float) -> None:
        """Wait up to `grace` seconds for the whole group to be gone, reaping Codex meanwhile."""
        loop = asyncio.get_running_loop()
        end = loop.time() + grace
        while loop.time() < end:
            if self._proc.returncode is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(self._proc.wait()), timeout=0.05)
            if not self._group_runs():
                return
            await asyncio.sleep(0.05)


def _binary() -> str:
    binary = shutil.which(CODEX)
    if binary is None:
        raise CodexError(f"the Codex CLI ({CODEX}) isn't installed, or isn't on PATH")
    return binary


async def _batches(stream: asyncio.StreamReader, deadline: float) -> AsyncGenerator[list[str]]:
    """The stream's lines, in the groups they arrived in. TimeoutError once `deadline` passes."""
    loop = asyncio.get_running_loop()
    lines: list[str] = []
    while True:
        if loop.time() >= deadline:
            raise TimeoutError
        try:
            line = await asyncio.wait_for(stream.readline(), timeout=FLUSH_S)
        except TimeoutError:
            line = None
        except ValueError:  # longer than the stream's limit, so readline dropped it
            if not lines or lines[-1] != LEFT_OUT:
                lines.append(LEFT_OUT)
            continue
        if line:
            lines.append(line.decode("utf-8", errors="replace"))
        if lines and (not line or len(lines) >= MAX_LINES):
            yield lines
            lines = []
        if line == b"":
            return


def _left(deadline: float) -> float:
    """Seconds until `deadline`, or none once it has passed."""
    return max(0.0, deadline - asyncio.get_running_loop().time())


def _error(last_lines: deque[str], code: int) -> str:
    """Why a review failed: Codex's own error line if it printed one, else that it was stopped,
    else the last thing it said."""
    said = [line.strip() for line in last_lines if line.strip()]
    if errors := [line for line in said if line.startswith("ERROR")]:
        return errors[-1]
    if code < 0:
        return f"codex review was stopped (signal {-code})"
    return said[-1] if said else f"codex review failed with exit code {code}"


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_TEXT else text[:MAX_OUTPUT_TEXT] + CLIPPED
