"""The summary of an eval: for each case and side, how its runs went, side by side, and each
run's outcome with links to its transcript and the final state of its repository. It is written
again after each run, so an interrupted eval keeps what finished."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from evals.cases import Case
from evals.runs import TOKENS, Run, median
from evals.workspace import Side

DEFAULT_EFFORT = "Claude Code's default"  # as the summary names the effort none was given


@dataclass(frozen=True)
class Eval:
    started: str  # UTC, as the results folder is named
    sides: tuple[Side, Side]
    cases: tuple[Case, ...]
    runs_a_side: int
    model: str | None  # as --model gave it
    effort: str | None  # as --effort gave it
    version: str  # Claude Code's, when the eval started
    same_templates: bool

    @property
    def planned(self) -> int:
        return len(self.cases) * len(self.sides) * self.runs_a_side


def model_of(runs: Sequence[Run]) -> str | None:
    """The model the eval's runs ran on: the one most of them did, each on one model."""
    counts = Counter(next(iter(r.models)) for r in runs if len(r.models) == 1)
    return counts.most_common(1)[0][0] if counts else None


def case_passes(runs: Sequence[Run], model: str | None) -> bool:
    """Whether a case passes on a side: it ran there, and every run passed."""
    return bool(runs) and all(r.passed(model) for r in runs)


def write(path: Path, info: Eval, runs: Sequence[Run]) -> None:
    path.write_text(render(info, runs, path.parent), encoding="utf-8")


def render(info: Eval, runs: Sequence[Run], folder: Path) -> str:
    model = model_of(runs)
    versions = sorted({v for r in runs for v in r.versions} or {info.version})
    lines = [
        f"# Eval {info.started}",
        "",
        *(f"- **{side.name.capitalize()}:** {side.label}" for side in info.sides),
        f"- **Model:** {model or info.model or 'none yet'}"
        f" · **Effort:** {info.effort or DEFAULT_EFFORT}"
        f" · **Claude Code:** {', '.join(versions)}",
        f"- **Runs:** {len(runs)} of {info.planned} done, {info.runs_a_side} on each side of each "
        "case, alternating sides",
    ]
    if info.same_templates:
        lines.append(
            "- **Both sides' templates are the same**, so what differs between them is noise"
        )
    for case in info.cases:
        lines += ["", *_case(case, info, [r for r in runs if r.case == case.name], model, folder)]
    return "\n".join(lines) + "\n"


def _case(
    case: Case, info: Eval, runs: Sequence[Run], model: str | None, folder: Path
) -> list[str]:
    by_side = {side.name: [r for r in runs if r.side == side.name] for side in info.sides}
    names = list(by_side)

    def row(label: str, cell: object) -> str:
        cells = [cell(by_side[name]) if callable(cell) else cell for name in names]
        return f"| {label} | " + " | ".join(str(c) for c in cells) + " |"

    def of(rs: Sequence[Run], value: str, unit: str = "") -> str:
        found = median(rs, value)
        if found is None:
            return "-"
        return _duration(found) if unit == "ms" else f"{found:,.0f}"

    lines = [
        f"## {case.name}",
        "",
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
        row("**Case passes**", lambda rs: "yes" if case_passes(rs, model) else "no"),
        row("Passed", lambda rs: f"{sum(r.passed(model) for r in rs)} of {len(rs)}"),
        row("Invalid", lambda rs: sum(bool(r.invalid_reasons(model)) for r in rs)),
        row("Agent steps (median)", lambda rs: of(rs, "steps")),
        row("Duration (median)", lambda rs: of(rs, "duration_ms", "ms")),
        *(row(f"Tokens, {kind} (median)", lambda rs, k=kind: of(rs, k)) for kind in TOKENS),
        row("Permission denials (median)", lambda rs: of(rs, "denials")),
        row("Errors (median)", lambda rs: of(rs, "errors")),
        *(
            row(
                o.label,
                lambda rs, label=o.label: (
                    f"{sum(r.observed.get(label, False) for r in rs)} of {len(rs)}"
                ),
            )
            for o in case.observations
        ),
        "",
        "| Run | Outcome | Steps | Duration | Tokens: input / output / cache writes / reads "
        "| Denials | Errors | Observed | |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(runs, key=lambda r: (r.number, names.index(r.side))):
        tokens = " / ".join(f"{r.tokens.get(kind, 0):,}" for kind in TOKENS)
        observed = "; ".join(label for label, seen in r.observed.items() if seen) or "-"
        base = r.folder.relative_to(folder).as_posix()
        links = f"[transcript]({base}/transcript.jsonl) · [final state]({base}/state.md)"
        lines.append(
            f"| {r.side} {r.number} | {_cell(_outcome(r, model))} | {r.steps} "
            f"| {_duration(r.duration_ms)} | {tokens} | {r.denials} | {r.errors} "
            f"| {_cell(observed)} | {links} |"
        )
    return lines


def _outcome(run: Run, model: str | None) -> str:
    if reasons := run.invalid_reasons(model):
        return "invalid: " + "; ".join(reasons)
    if run.failed:
        return "failed: " + "; ".join(run.failed)
    return "passed"


def _duration(ms: float) -> str:
    seconds = round(ms / 1000)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def _cell(text: str) -> str:
    """Text as one Markdown table cell: a `|` in it doesn't end the cell."""
    return text.replace("|", "\\|")
