"""One run of a case on one side: its repository, the steps before its session, the session on
the case's prompt, its pass check, and what it shows.

A run passes when it is valid, its case's pass check holds on the repository it leaves, and its
session didn't end in an error or a timeout. It is invalid when it loaded any of the developer's
own configuration, its setup failed, the service rather than the agent cut it short, or it ran
on a different model from the eval's other runs, which only the eval as a whole can tell.
"""

from __future__ import annotations

import statistics
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from evals import agent, workspace
from evals.cases import Case
from evals.errors import EvalError

RUN_TIMEOUT_S = 20 * 60.0  # how long a run's session may take
SCRIPT_TIMEOUT_S = 60.0  # how long a case's setup or pass check may take
TOKENS = {  # each kind of token, as the summary names it, and as `usage` does
    "input": "input_tokens",
    "output": "output_tokens",
    "cache writes": "cache_creation_input_tokens",
    "cache reads": "cache_read_input_tokens",
}


@dataclass
class Run:
    case: str
    side: str
    number: int  # its number among the case's runs on its side, from 1
    folder: Path  # its results: transcript, the repository's state at start and end, reply
    models: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    invalid: list[str] = field(default_factory=list)  # why it doesn't count, but its model
    failed: list[str] = field(default_factory=list)  # why it didn't pass, though valid
    steps: int = 0  # the agent's
    duration_ms: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TOKENS, 0))
    denials: int = 0
    errors: int = 0  # tool calls that ended in an error
    observed: dict[str, bool] = field(default_factory=dict)  # by observation's name

    def invalid_reasons(self, model: str | None) -> list[str]:
        """Why the run doesn't count, given the model the eval's runs ran on."""
        if model is None or not self.models or self.models == {model}:
            return self.invalid
        return [*self.invalid, f"ran on {', '.join(sorted(self.models))}, not {model}"]

    def passed(self, model: str | None) -> bool:
        return not self.invalid_reasons(model) and not self.failed


def run(
    case: Case,
    side: workspace.Side,
    number: int,
    folder: Path,
    *,
    own: agent.Own,
    model: str | None,
    effort: str | None,
) -> Run:
    """Run `case` once on `side`, keeping its results in `folder`."""
    folder.mkdir(parents=True)
    record = Run(case.name, side.name, number, folder)
    private = workspace.private_folder()
    repo = workspace.build(private, case, side)
    env = workspace.run_env(private)
    if case.setup is not None:
        ok, output = _script(case.setup, repo, env)
        if not ok:
            record.invalid.append(f"its setup failed: {output or 'no reason given'}")
            (folder / "end.md").write_text(_state(repo, env), encoding="utf-8")
            return record
    (folder / "start.md").write_text(_state(repo, env), encoding="utf-8")
    end = agent.session(
        agent.argv(repo, model=model, effort=effort),
        case.prompt,
        cwd=repo,
        env=env,
        transcript=folder / "transcript.jsonl",
        stderr=folder / "claude-stderr.log",
        timeout=RUN_TIMEOUT_S,
    )
    (folder / "end.md").write_text(_state(repo, env), encoding="utf-8")
    (folder / "reply.md").write_text(agent.reply(end) or "", encoding="utf-8")
    _count(record, end)
    first = agent.first_shell_command(end.events)
    record.observed = {o.name: o.holds(first) for o in case.observations}
    if loaded := agent.developers_own(end.events, own, repo):
        record.invalid.append(f"loaded the developer's own {', '.join(loaded)}")
    if service := agent.cut_short_by_service(end):
        record.invalid.append(service)
    elif why := _ended_badly(end):
        record.failed.append(why)
    else:
        ok, output = _script(case.check, repo, {**env, "EVAL_RUN": str(folder)})
        if not ok:
            record.failed.append(f"pass check: {output or 'failed'}")
    return record


def median(runs: Sequence[Run], value: str) -> float | None:
    """The median of one of the runs' numbers: an attribute, or a kind of token."""
    values = [r.tokens[value] if value in TOKENS else getattr(r, value) for r in runs]
    return statistics.median(values) if values else None


def _count(record: Run, end: agent.SessionEnd) -> None:
    result = end.result or {}
    usage = result["usage"] if isinstance(result.get("usage"), dict) else {}
    record.models = agent.models(end.events)
    record.versions = agent.versions(end.events)
    record.steps = int(result.get("num_turns") or 0)
    record.duration_ms = int(result.get("duration_ms") or 0)
    record.tokens = {kind: int(usage.get(key) or 0) for kind, key in TOKENS.items()}
    record.denials = len(result.get("permission_denials") or [])
    record.errors = agent.tool_errors(end.events)


def _ended_badly(end: agent.SessionEnd) -> str | None:
    """Why the session didn't end as the agent meant it to, or None when it did."""
    if end.timed_out:
        return f"timed out after {RUN_TIMEOUT_S / 60:g} minutes"
    if end.result is None:
        return f"Claude Code ended with exit code {end.exit_code}, and no result"
    if end.result.get("is_error"):
        return f"ended in an error: {end.result.get('subtype')}"
    return None


def _script(script: Path, repo: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    """Run a case's script with `sh` in the repository: whether it exited 0, and what it
    printed, on one line."""
    try:
        done = subprocess.run(
            ["sh", str(script)],
            cwd=repo,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return done.returncode == 0, " ".join((done.stdout + done.stderr).split())


def _state(repo: Path, env: Mapping[str, str]) -> str:
    try:
        return f"# {repo}\n\n" + workspace.state(repo, env)
    except EvalError as exc:
        return f"# {repo}\n\nIts state can't be read: {exc}\n"
