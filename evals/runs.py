"""One run of a case on one side: its repository, its session's turns and the steps between
them, its checks, and what it shows.

A run passes when it is valid, its case's pass check holds on the repository it leaves, and no
turn ended in an error or a timeout. It is invalid when it loaded any of the developer's own
configuration, a turn's check failed, a step the eval takes failed, the service rather than the
agent cut a turn short, or it ran on a different model from the eval's other runs (which only
the eval as a whole can tell). A run stops at the first turn that makes it invalid or fail.
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

TURN_TIMEOUT_S = 20 * 60.0  # how long one turn may take
CHECK_TIMEOUT_S = 60.0  # how long a check or a step may take


@dataclass
class Run:
    case: str
    side: str
    number: int  # its number among the case's runs on its side, from 1
    folder: Path  # its results: transcript, final state, each turn's refs and reply
    repository: Path | None = None
    models: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    invalid: list[str] = field(default_factory=list)  # why it doesn't count, but its model
    failed: list[str] = field(default_factory=list)  # why it didn't pass, though valid
    steps: int = 0  # the agent's, over all its turns
    duration_ms: int = 0
    tokens: dict[str, int] = field(default_factory=dict)  # by kind, over all its turns
    denials: int = 0
    errors: int = 0  # tool calls that ended in an error
    cost_usd: float = 0.0  # Claude Code's estimate
    observed: dict[str, bool] = field(default_factory=dict)  # by observation's label

    def invalid_reasons(self, model: str | None) -> list[str]:
        """Why the run doesn't count, given the model the eval's runs ran on."""
        if model is None or not self.models or self.models == {model}:
            return self.invalid
        return [*self.invalid, f"ran on {', '.join(sorted(self.models))}, not {model}"]

    def passed(self, model: str | None) -> bool:
        return not self.invalid_reasons(model) and not self.failed


TOKENS = {  # each kind of token, as the summary names it, and as `usage` does
    "input": "input_tokens",
    "output": "output_tokens",
    "cache writes": "cache_creation_input_tokens",
    "cache reads": "cache_read_input_tokens",
}


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
    record = Run(case.name, side.name, number, folder, tokens=dict.fromkeys(TOKENS, 0))
    private = workspace.private_folder()
    repo = record.repository = workspace.build(private, case, side)
    env = workspace.run_env(private)
    events: list[dict[str, object]] = []
    args = agent.argv(repo, model=model, effort=effort)
    session: agent.Session | None = None
    ended = False
    try:
        for n, turn in enumerate(case.turns, start=1):
            turn_folder = folder / f"turn-{n}"
            turn_folder.mkdir()
            for step in turn.before:
                ok, output = _script(list(step), repo, env)
                if not ok:
                    record.invalid.append(f"turn {n}'s step `{' '.join(step)}` failed: {output}")
                    return record
            if session is None:
                session = agent.Session(
                    args, repo, env, folder / "transcript.jsonl", folder / "claude-stderr.log"
                )
            (turn_folder / "refs-before").write_text(workspace.refs(repo, env), encoding="utf-8")
            end = session.turn(turn.prompt, timeout=TURN_TIMEOUT_S)
            events += end.events
            (turn_folder / "refs-after").write_text(workspace.refs(repo, env), encoding="utf-8")
            reply = agent.reply(end)
            (turn_folder / "reply.md").write_text(reply or "", encoding="utf-8")
            _count(record, end)
            first = agent.first_shell_command(end.events)
            for observation in case.observations:
                if observation.turn == n:
                    record.observed[observation.label] = observation.holds(first, reply)
            if why := _ended_badly(n, end):
                (record.invalid if why[0] else record.failed).append(why[1])
                return record
            if turn.check is not None:
                ok, output = _check(turn.check, repo, env, folder, turn_folder)
                if not ok:
                    record.invalid.append(f"turn {n}'s check: {output or 'failed'}")
                    return record
        if session is not None:
            session.close()
        ended = True
        ok, output = _check(case.passes, repo, env, folder, None)
        if not ok:
            record.failed.append(f"pass check: {output or 'failed'}")
        return record
    finally:
        if session is not None and not ended:
            session.stop()
        record.models = agent.models(events)
        record.versions = agent.versions(events)
        if loaded := agent.developers_own(events, own, repo):
            record.invalid.insert(0, f"loaded the developer's own {', '.join(loaded)}")
        for observation in case.observations:
            record.observed.setdefault(observation.label, False)
        (folder / "state.md").write_text(_state(repo, env), encoding="utf-8")


def median(runs: Sequence[Run], value: str) -> float | None:
    """The median of one of the runs' numbers: an attribute, or a kind of token."""
    values = [r.tokens[value] if value in TOKENS else getattr(r, value) for r in runs]
    return statistics.median(values) if values else None


def _count(record: Run, end: agent.TurnEnd) -> None:
    result = end.result or {}
    usage = result["usage"] if isinstance(result.get("usage"), dict) else {}
    record.steps += int(result.get("num_turns") or 0)
    record.duration_ms += int(result.get("duration_ms") or 0)
    for kind, key in TOKENS.items():
        record.tokens[kind] += int(usage.get(key) or 0)
    record.denials += len(result.get("permission_denials") or [])
    record.errors += agent.tool_errors(end.events)
    record.cost_usd = float(result.get("total_cost_usd") or record.cost_usd)  # the session's


def _ended_badly(n: int, end: agent.TurnEnd) -> tuple[bool, str] | None:
    """Why turn `n` didn't end as the agent meant, and whether that makes the run invalid
    (True) or fail (False); None when it ended well."""
    if service := agent.cut_short_by_service(end):
        return True, f"turn {n}: {service}"
    if end.timed_out:
        return False, f"turn {n} timed out after {TURN_TIMEOUT_S / 60:g} minutes"
    if end.exit_code is not None:
        return False, f"Claude Code ended during turn {n}, with exit code {end.exit_code}"
    if end.result is not None and end.result.get("is_error"):
        return False, f"turn {n} ended in an error: {end.result.get('subtype')}"
    return None


def _check(
    script: Path, repo: Path, env: Mapping[str, str], run: Path, turn: Path | None
) -> tuple[bool, str]:
    extra = {"EVAL_RUN": str(run), **({"EVAL_TURN": str(turn)} if turn else {})}
    return _script(["sh", str(script)], repo, {**env, **extra})


def _script(args: list[str], repo: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    """Run a check or step in the repository: whether it exited 0, and what it printed."""
    try:
        done = subprocess.run(
            args,
            cwd=repo,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return done.returncode == 0, " ".join((done.stdout + done.stderr).split())


def _state(repo: Path | None, env: Mapping[str, str]) -> str:
    if repo is None or not repo.is_dir():
        return "The run's repository wasn't made.\n"
    try:
        return f"# {repo}\n\n" + workspace.state(repo, env)
    except EvalError as exc:
        return f"# {repo}\n\nIts state can't be read: {exc}\n"
