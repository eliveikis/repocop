"""The order of a repository's changes by their `depends-on`, as RepoCop reads it and as
the template's `specs/changes/backlog.sh` draws it: the same changes give both the same levels and
the same refusals."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT
from repocop.services import backlog

SCRIPT = PROJECT_ROOT / "templates" / "default-repo" / "specs" / "changes" / "backlog.sh"
# The awks the script must work with: Debian's default, and GNU awk held to POSIX.
AWKS = {"mawk": ["mawk"], "posix-awk": ["gawk", "--posix"]}
DONE = "2026-10-14T150616Z-"  # before an archived change's file name

Changes = dict[str, str]


def needs(*names: str) -> str:
    """A change that lists `names` in its depends-on."""
    listed = "".join(f"  - {name}\n" for name in names)
    return f"---\ndepends-on:\n{listed}---\n## Requirement\n\nSomething.\n"


ORDERED: dict[str, tuple[Changes, list[str], list[list[str]]]] = {
    "nothing to do": ({}, [], []),
    "no dependencies": ({"a.md": "", "b.md": "## Requirement\n\nB.\n"}, [], [["a", "b"]]),
    "a chain": ({"a.md": needs("b"), "b.md": needs("c"), "c.md": ""}, [], [["c"], ["b"], ["a"]]),
    "the longest chain sets the level": (
        {"a.md": "", "b.md": needs("a"), "c.md": "", "d.md": needs("b", "c")},
        [],
        [["a", "c"], ["b"], ["d"]],
    ),
    "a delivered dependency": ({"a.md": needs("x", "y")}, [f"{DONE}x.md", "y.md"], [["a"]]),
    "names without the id": (
        {"a.md": needs("bulk-import", "old"), "req-12-bulk-import.md": ""},
        [f"{DONE}req-3-old.md"],
        [["bulk-import"], ["a"]],
    ),
    "front matter as people write it": (
        {
            "a.md": "---\r\ntitle: A\r\ndepends-on:\r\n  # first\r\n\r\n  - b\r\n- c\r\n"
            "owner: me\r\n---\r\nText.\r\n",
            "b.md": "",
            "c.md": "",
        },
        [],
        [["b", "c"], ["a"]],
    ),
    "a rule further down isn't front matter": (
        {"a.md": "Intro.\n\n---\ndepends-on:\n  - nope\n---\n"},
        [],
        [["a"]],
    ),
}

REFUSED: dict[str, tuple[Changes, list[str], list[str]]] = {
    "a name that matches nothing": (
        {"a.md": needs("nope")},
        [],
        ['a: needs "nope", which matches no change'],
    ),
    "a name that matches two changes": (
        {"a.md": needs("x"), "x.md": "", "req-3-x.md": ""},
        [],
        ['a: needs "x", which matches more than one change'],
    ),
    "a name that matches a change and a delivered one": (
        {"a.md": needs("x"), "x.md": ""},
        [f"{DONE}x.md"],
        ['a: needs "x", which matches more than one change'],
    ),
    "a change that needs itself": ({"a.md": needs("a")}, [], ["a: needs itself"]),
    "a cycle": (
        {"a.md": needs("b"), "b.md": needs("c"), "c.md": needs("a"), "d.md": needs("a")},
        [],
        ["a, b, c: depend on one another in a cycle"],
    ),
    "names on the depends-on line": (
        {"a.md": "---\ndepends-on: [b]\n---\n", "b.md": ""},
        [],
        ['a: lists its depends-on on one line; put each name on a line of its own, after "- "'],
    ),
    "front matter that never closes": (
        {"a.md": "---\ndepends-on:\n  - b\n", "b.md": ""},
        [],
        ["a: its front matter has no closing ---"],
    ),
    "two names on a line": (
        {"a.md": needs("b c"), "b.md": "", "c.md": ""},
        [],
        ['a: has a line under depends-on that is not "- <name>": "  - b c"'],
    ),
    "a name without its dash": (
        {"a.md": "---\ndepends-on:\n  b\nowner: me\n---\n", "b.md": ""},
        [],
        ['a: has a line under depends-on that is not "- <name>": "  b"'],
    ),
    "a name without its dash or indent": (
        {"a.md": "---\ndepends-on:\nb\n---\n", "b.md": ""},
        [],
        ['a: has a line under depends-on that is not "- <name>": "b"'],
    ),
    "depends-on twice": (
        {"a.md": "---\ndepends-on:\n  - b\ndepends-on:\n  - c\n---\n", "b.md": "", "c.md": ""},
        [],
        ["a: has depends-on twice"],
    ),
    "several problems": (
        {"a.md": needs("nope"), "b.md": needs("b"), "c.md": "---\n"},
        [],
        [
            "c: its front matter has no closing ---",
            'a: needs "nope", which matches no change',
            "b: needs itself",
        ],
    ),
}


@pytest.fixture(params=sorted(AWKS))
def awk(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A folder to put first on PATH, whose `awk` is one of AWKS."""
    command = AWKS[request.param]
    if shutil.which(command[0]) is None:
        pytest.skip(f"{command[0]} isn't installed")
    folder = tmp_path / "bin"
    folder.mkdir()
    shim = folder / "awk"
    shim.write_text(f'#!/bin/sh\nexec {" ".join(command)} "$@"\n')
    shim.chmod(0o755)
    return folder


def lay_out(root: Path, todo: Changes, archived: list[str]) -> Path:
    """`specs/changes/` under `root`, with the script and these changes."""
    changes = root / "repo" / "specs" / "changes"
    for folder in ("todo", "archive"):
        (changes / folder).mkdir(parents=True)
    for file, text in todo.items():
        (changes / "todo" / file).write_bytes(text.encode())
    for file in archived:
        (changes / "archive" / file).write_text("Done.\n")
    shutil.copy2(SCRIPT, changes / "backlog.sh")
    return changes


def backlog_sh(
    changes: Path, awk: Path, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{awk}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        [changes / "backlog.sh", *args],
        cwd=cwd or changes.parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def drawn_levels(text: str) -> list[list[str]]:
    """The names listed under each level's heading in backlog.md."""
    levels: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            levels.append([])
        elif line.startswith("- [") and levels:
            levels[-1].append(line[3 : line.index("](")])
    return levels


@pytest.mark.parametrize("case", sorted(ORDERED))
def test_backlog_script_and_repocop_order_changes_alike(
    case: str, awk: Path, tmp_path: Path
) -> None:
    todo, archived, levels = ORDERED[case]
    changes = lay_out(tmp_path, todo, archived)
    ran = backlog_sh(changes, awk)
    assert (ran.returncode, ran.stderr) == (0, "")
    assert drawn_levels((changes / "backlog.md").read_text()) == levels
    ordered = backlog.order(todo, archived)
    assert [[change.name for change in level] for level in ordered.levels] == levels
    assert ordered.problems == ()


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_backlog_script_and_repocop_refuse_alike(case: str, awk: Path, tmp_path: Path) -> None:
    todo, archived, problems = REFUSED[case]
    changes = lay_out(tmp_path, todo, archived)
    (changes / "backlog.md").write_text("as drawn before\n")
    ran = backlog_sh(changes, awk)
    assert ran.returncode == 1
    assert ran.stderr.splitlines() == problems
    assert (changes / "backlog.md").read_text() == "as drawn before\n"
    assert backlog_sh(changes, awk, "--check").returncode == 1
    assert [str(problem) for problem in backlog.order(todo, archived).problems] == problems


def test_backlog_script_draws_each_change_and_its_undelivered_dependencies(
    awk: Path, tmp_path: Path
) -> None:
    todo = {"a.md": needs("b", "x"), "b.md": needs("c"), "c.md": "", "my notes.md": ""}
    changes = lay_out(tmp_path, todo, [f"{DONE}x.md"])
    assert backlog_sh(changes, awk).returncode == 0
    drawn = (changes / "backlog.md").read_text()
    chart = drawn[drawn.index("```mermaid\n") : drawn.index("\n```\n")]
    assert [line.strip() for line in chart.splitlines()[1:]] == [
        "flowchart LR",
        'c1["a"]',
        'c2["b"]',
        'c3["c"]',
        'c4["my notes"]',
        "c2 --> c1",
        "c3 --> c2",
    ]
    assert "- [a](todo/a.md)" in drawn
    assert "- [my notes](todo/my%20notes.md)" in drawn


def test_backlog_script_check_writes_nothing(awk: Path, tmp_path: Path) -> None:
    changes = lay_out(tmp_path, {"a.md": needs("b"), "b.md": ""}, [])
    ran = backlog_sh(changes, awk, "--check")
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, "", "")
    assert not (changes / "backlog.md").exists()


def test_backlog_script_runs_from_any_folder(awk: Path, tmp_path: Path) -> None:
    changes = lay_out(tmp_path, {"a.md": needs("b"), "b.md": ""}, [])
    assert backlog_sh(changes, awk, cwd=changes / "todo").returncode == 0
    assert drawn_levels((changes / "backlog.md").read_text()) == [["b"], ["a"]]


def test_backlog_script_refuses_an_unknown_option(awk: Path, tmp_path: Path) -> None:
    changes = lay_out(tmp_path, {}, [])
    ran = backlog_sh(changes, awk, "--draw")
    assert ran.returncode == 2
    assert "usage" in ran.stderr


def test_repocop_lists_apart_the_changes_a_problem_holds_up() -> None:
    todo = {
        "a.md": needs("b"),
        "b.md": needs("a"),
        "c.md": needs("a"),
        "d.md": needs("nope"),
        "e.md": needs("d"),
        "f.md": needs("g"),
        "g.md": "",
    }
    ordered = backlog.order(todo, [])
    assert [change.name for change in ordered.apart] == ["a", "b", "c", "d", "e"]
    assert [[change.name for change in level] for level in ordered.levels] == [["g"], ["f"]]
