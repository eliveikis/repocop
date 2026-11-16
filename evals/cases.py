"""The cases an eval runs, each a folder in `evals/cases/` holding a `case.toml` and the files it
names.

`case.toml` has these keys, and paths in it are relative to the case's folder. A path may lead
into another case's folder, as a case built on another takes its pieces, but never out of
`evals/cases/`:

- `files` (optional): a folder of the case's own files, which its repository starts with.
- `passes`: the pass check, a shell script.
- `[[turns]]`, one or more, each sent to the agent in one session, in order:
  - `prompt`: a file holding what the turn says to the agent.
  - `before` (optional): steps the eval takes in the repository before the turn, without telling
    the agent, each an argv list. Turn 1's are taken before the session starts.
  - `check` (optional): a shell script that must hold after the turn, or the run is invalid.
- `[[observations]]` (optional), each `turn` (its number) and `observe`: a TOML file naming what
  is observed of that turn's transcript (`name`) and how, by one regular expression searched in
  the turn's first shell command (`first_command`) or in its last reply (`reply`). An
  observation doesn't count toward passing.

A check holds when its script exits 0, and what it prints says why it doesn't. It runs with `sh`
in the run's repository, with `EVAL_RUN` naming the run's results folder, where each turn has a
folder, `turn-<n>/`, holding `refs-before` and `refs-after`, the repository's refs before and
after the turn (`<commit> HEAD`, then `<commit> refs/heads/<branch>` for each branch), and
`reply.md`, the turn's last reply. A turn's check also has `EVAL_TURN`, naming its turn's folder.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.errors import EvalError

CASES = Path(__file__).resolve().parent / "cases"
DEFINITION = "case.toml"
OBSERVATION_KINDS = ("first_command", "reply")


@dataclass(frozen=True)
class Turn:
    prompt: str
    before: tuple[tuple[str, ...], ...] = ()
    check: Path | None = None


@dataclass(frozen=True)
class Observation:
    turn: int
    name: str
    kind: str  # one of OBSERVATION_KINDS
    pattern: re.Pattern[str]

    @property
    def label(self) -> str:
        return f"turn {self.turn}: {self.name}"

    def holds(self, first_command: str | None, reply: str | None) -> bool:
        """Whether the turn's first shell command or its last reply, as the kind says, matches."""
        text = first_command if self.kind == "first_command" else reply
        return text is not None and self.pattern.search(text) is not None


@dataclass(frozen=True)
class Case:
    name: str
    turns: tuple[Turn, ...]
    passes: Path
    files: Path | None = None
    observations: tuple[Observation, ...] = ()


def names() -> list[str]:
    """Every case's name, in order."""
    return sorted(path.parent.name for path in CASES.glob(f"*/{DEFINITION}"))


def load(selected: Sequence[str] = ()) -> list[Case]:
    """The cases named, in the order named, or every case when none is. Refused, naming the
    cases there are, when one isn't a case, and when a case's definition is wrong."""
    known = names()
    unknown = [name for name in selected if name not in known]
    if unknown:
        raise EvalError(f"no case named {', '.join(unknown)}; the cases are: {', '.join(known)}")
    return [_load(name) for name in dict.fromkeys(selected or known)]


def _load(name: str) -> Case:
    folder = CASES / name
    data = _toml(folder / DEFINITION)
    where = f"case {name}"
    _keys(data, where, required={"passes", "turns"}, optional={"files", "observations"})
    turns = tuple(
        _turn(folder, f"{where}, turn {n}", raw) for n, raw in _tables(data, "turns", where)
    )
    if not turns:
        raise EvalError(f"{where} has no turns")
    files = _path(folder, data["files"], f"{where}'s files") if "files" in data else None
    if files is not None and not files.is_dir():
        raise EvalError(f"{where}'s files, {files}, isn't a folder")
    observations = tuple(
        _observation(folder, f"{where}, observation {n}", raw, len(turns))
        for n, raw in _tables(data, "observations", where)
    )
    return Case(
        name, turns, _file(folder, data["passes"], f"{where}'s pass check"), files, observations
    )


def _turn(folder: Path, where: str, raw: dict[str, Any]) -> Turn:
    _keys(raw, where, required={"prompt"}, optional={"before", "check"})
    prompt = _file(folder, raw["prompt"], f"{where}'s prompt").read_text(encoding="utf-8").strip()
    if not prompt:
        raise EvalError(f"{where}'s prompt is empty")
    before = raw.get("before", [])
    if not isinstance(before, list) or not all(
        isinstance(step, list) and step and all(isinstance(arg, str) for arg in step)
        for step in before
    ):
        raise EvalError(f"{where}'s before must be a list of steps, each an argv list")
    check = _file(folder, raw["check"], f"{where}'s check") if "check" in raw else None
    return Turn(prompt, tuple(tuple(step) for step in before), check)


def _observation(folder: Path, where: str, raw: dict[str, Any], turns: int) -> Observation:
    _keys(raw, where, required={"turn", "observe"}, optional=set())
    turn = raw["turn"]
    if not isinstance(turn, int) or not 1 <= turn <= turns:
        raise EvalError(f"{where}'s turn must be a turn's number, 1 to {turns}")
    path = _file(folder, raw["observe"], f"{where}'s observe")
    spec = _toml(path)
    kinds = [kind for kind in OBSERVATION_KINDS if kind in spec]
    _keys(spec, str(path), required={"name"}, optional=set(OBSERVATION_KINDS))
    if len(kinds) != 1 or not all(isinstance(spec[key], str) for key in ("name", *kinds)):
        raise EvalError(f"{path} must name what it observes and give one of {OBSERVATION_KINDS}")
    try:
        pattern = re.compile(spec[kinds[0]])
    except re.error as exc:
        raise EvalError(f"{path}'s {kinds[0]} isn't a regular expression: {exc}") from exc
    return Observation(turn, spec["name"], kinds[0], pattern)


def _toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise EvalError(f"can't read {path}: {exc}") from exc


def _keys(data: dict[str, Any], where: str, *, required: set[str], optional: set[str]) -> None:
    missing, unknown = required - set(data), set(data) - required - optional
    if missing or unknown:
        problems = [f"lacks {', '.join(sorted(missing))}"] if missing else []
        problems += [f"has unknown {', '.join(sorted(unknown))}"] if unknown else []
        raise EvalError(f"{where} {' and '.join(problems)}")


def _tables(data: dict[str, Any], key: str, where: str) -> list[tuple[int, dict[str, Any]]]:
    tables = data.get(key, [])
    if not isinstance(tables, list) or not all(isinstance(table, dict) for table in tables):
        raise EvalError(f"{where}'s {key} must be tables, as [[{key}]]")
    return list(enumerate(tables, start=1))


def _path(folder: Path, value: object, what: str) -> Path:
    """`value`, a path relative to the case's folder, resolved; refused out of `evals/cases/`."""
    if not isinstance(value, str) or not value:
        raise EvalError(f"{what} must be a path")
    path = (folder / value).resolve()
    if not path.is_relative_to(CASES):
        raise EvalError(f"{what}, {value}, leads out of {CASES}")
    return path


def _file(folder: Path, value: object, what: str) -> Path:
    path = _path(folder, value, what)
    if not path.is_file():
        raise EvalError(f"{what}, {value}, isn't a file")
    return path
