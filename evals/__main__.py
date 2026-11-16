"""Run the eval: each case in `evals/cases/`, on the repo template before a change and after it,
and write a summary comparing the two in `evals/results/<UTC time>/`.

    uv run python -m evals [--before REF] [--after REF] [--case NAME]... [--runs N]
                           [--model NAME] [--effort LEVEL]

Before is the default branch on `origin` as last fetched, and after the working tree,
uncommitted changes included, unless a ref is named. Each case runs `--runs` times (5) on each
side, one run at a time, alternating sides, with the same model and effort on both: Claude
Code's defaults unless named. It exits 0 only when every case passes on the after side, 1 when
one doesn't, and 2 when the eval refuses to run, saying why.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import sys
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from evals import agent, cases, runs, summary, workspace
from evals.errors import EvalError

ROOT = Path(__file__).resolve().parent.parent  # the repository whose template is evaluated
RESULTS = Path(__file__).resolve().parent / "results"
DEFAULT_RUNS = 5
WORKING_TREE = "the working tree, uncommitted changes included"


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT, results: Path = RESULTS) -> int:
    args = _parser().parse_args(argv)
    try:
        with _only_eval(results):
            return _run(args, root, results)
    except EvalError as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace, root: Path, results: Path) -> int:
    selected = cases.load(args.case)
    before_ref = args.before or workspace.default_branch(root)
    before = workspace.resolve(root, before_ref)
    after = workspace.resolve(root, args.after) if args.after else None
    workspace.check_temp_folder(root)
    env = workspace.run_env(None)
    version = agent.check_ready(env)
    own = agent.Own.read(agent.config_folder(env))
    for past in workspace.remove_past():
        print(f"Removed {past}, which a past eval left")
    snapshots = workspace.private_folder()
    sides = (
        workspace.Side(
            "before",
            f"{before_ref} at {before[:7]}",
            workspace.snapshot_at(root, before, snapshots / "before"),
        ),
        workspace.Side(
            "after",
            f"{args.after} at {after[:7]}" if after else WORKING_TREE,
            workspace.snapshot_at(root, after, snapshots / "after")
            if after
            else workspace.snapshot_working_tree(root, snapshots / "after"),
        ),
    )
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    info = summary.Eval(
        started,
        sides,
        tuple(selected),
        args.runs,
        args.model,
        args.effort,
        version,
        workspace.same_templates(sides[0].template, sides[1].template),
    )
    folder = results / started
    folder.mkdir(parents=True)
    report = folder / "summary.md"
    print(
        f"The eval makes {info.planned} runs: {len(selected)} case(s), {args.runs} on each side, "
        f"one at a time, before: {sides[0].label}, after: {sides[1].label}."
    )
    if info.same_templates:
        print("Both sides' templates are the same, so what differs between them is noise.")
    done: list[runs.Run] = []
    summary.write(report, info, done)
    try:
        for number in range(1, args.runs + 1):
            for case in selected:
                for side in sides:
                    where = folder / "runs" / case.name / f"{side.name}-{number}"
                    record = runs.run(
                        case, side, number, where, own=own, model=args.model, effort=args.effort
                    )
                    done.append(record)
                    summary.write(report, info, done)
                    model = summary.model_of(done)
                    outcome = "passed" if record.passed(model) else "didn't pass"
                    print(
                        f"[{len(done)}/{info.planned}] {case.name}, {side.name} {number}: {outcome}"
                    )
    except KeyboardInterrupt:
        print(f"Interrupted. What finished is in {report}")
        return 130
    print(f"Summary: {report}")
    model = summary.model_of(done)
    after_runs = [r for r in done if r.side == "after"]
    passing = all(
        summary.case_passes([r for r in after_runs if r.case == case.name], model)
        for case in selected
    )
    return 0 if passing else 1


@contextlib.contextmanager
def _only_eval(results: Path) -> Iterator[None]:
    """Hold the eval's lock while it runs; refused while another eval holds it."""
    results.mkdir(parents=True, exist_ok=True)
    with (results / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise EvalError("another eval is running: wait for it to end") from None
        yield


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make eval ARGS=...", description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    parser.add_argument("--before", metavar="REF", help="the before side (origin's default branch)")
    parser.add_argument("--after", metavar="REF", help="the after side (the working tree)")
    parser.add_argument("--case", metavar="NAME", action="append", default=[], help="a case to run")
    parser.add_argument(
        "--runs", type=_positive, default=DEFAULT_RUNS, help="runs on each side (5)"
    )
    parser.add_argument("--model", metavar="NAME", help="the model every run uses")
    parser.add_argument("--effort", metavar="LEVEL", help="the effort every run uses")
    return parser


if __name__ == "__main__":
    sys.exit(main())
