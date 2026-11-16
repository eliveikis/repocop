"""The cases an eval runs, each a folder in `evals/cases/` holding a `case.toml` and the files it
names. Its keys, where a path is relative to the case's folder and stays inside it:

- `prompt`: what the run says to the agent, its one prompt.
- `check`: the pass check, a shell script run on the repository the session leaves, which decides
  whether the run passed.
- `files` (optional): a folder of the case's own files, which its repository starts with.
- `setup` (optional): a shell script of the steps the eval takes in the repository before the
  session starts, without telling the agent.
- `[[observations]]` (optional): each a `name` for what is observed of the run's transcript and
  `first_command`, a regular expression searched in the agent's first shell command. An
  observation doesn't count toward passing.

A script runs with `sh` in the run's repository, and succeeds when it exits 0; what it prints
says why it didn't. The pass check has `EVAL_RUN`, naming the run's results folder, which holds
`start.md` and `end.md`, records of the repository's state as the session started and as it
ended, equal when the run left the repository as it found it, and `reply.md`, the agent's last
reply.
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


@dataclass(frozen=True)
class Observation:
    name: str
    first_command: re.Pattern[str]

    def holds(self, first_command: str | None) -> bool:
        return first_command is not None and self.first_command.search(first_command) is not None


@dataclass(frozen=True)
class Case:
    name: str
    prompt: str
    check: Path
    files: Path | None = None
    setup: Path | None = None
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
    where = f"case {name}"
    try:
        data = tomllib.loads((folder / DEFINITION).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise EvalError(f"can't read {where}: {exc}") from exc
    _keys(data, where, required={"prompt", "check"}, optional={"files", "setup", "observations"})
    prompt = data["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise EvalError(f"{where}'s prompt must be text")
    files = _path(folder, data["files"], f"{where}'s files") if "files" in data else None
    if files is not None and not files.is_dir():
        raise EvalError(f"{where}'s files, {data['files']}, isn't a folder")
    setup = _file(folder, data["setup"], f"{where}'s setup") if "setup" in data else None
    observations = data.get("observations", [])
    if not isinstance(observations, list) or not all(isinstance(o, dict) for o in observations):
        raise EvalError(f"{where}'s observations must be tables, as [[observations]]")
    return Case(
        name,
        prompt.strip(),
        _file(folder, data["check"], f"{where}'s pass check"),
        files,
        setup,
        tuple(_observation(f"{where}, observation {n}", o) for n, o in enumerate(observations, 1)),
    )


def _observation(where: str, raw: dict[str, Any]) -> Observation:
    _keys(raw, where, required={"name", "first_command"}, optional=set())
    if not all(isinstance(raw[key], str) for key in ("name", "first_command")):
        raise EvalError(f"{where}'s name and first_command must be text")
    try:
        return Observation(raw["name"], re.compile(raw["first_command"]))
    except re.error as exc:
        raise EvalError(f"{where}'s first_command isn't a regular expression: {exc}") from exc


def _keys(data: dict[str, Any], where: str, *, required: set[str], optional: set[str]) -> None:
    missing, unknown = required - set(data), set(data) - required - optional
    if missing or unknown:
        problems = [f"lacks {', '.join(sorted(missing))}"] if missing else []
        problems += [f"has unknown {', '.join(sorted(unknown))}"] if unknown else []
        raise EvalError(f"{where} {' and '.join(problems)}")


def _path(folder: Path, value: object, what: str) -> Path:
    """`value`, a path relative to the case's folder, resolved; refused out of that folder."""
    if not isinstance(value, str) or not value:
        raise EvalError(f"{what} must be a path")
    path = (folder / value).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise EvalError(f"{what}, {value}, leads out of the case's folder")
    return path


def _file(folder: Path, value: object, what: str) -> Path:
    path = _path(folder, value, what)
    if not path.is_file():
        raise EvalError(f"{what}, {value}, isn't a file")
    return path
