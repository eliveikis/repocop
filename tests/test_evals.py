"""The agent eval, `make eval`, driven from its entry point with Claude Code faked: how it lays
out each run, isolates it, scores it and sums it up, and what it refuses."""

import fcntl
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from evals.__main__ import main as run_eval
from repocop.config import PROJECT_ROOT
from tests.conftest import run_git
from tests.fakes.fake_claude import FakeClaude

TEMPLATE = PROJECT_ROOT / "templates" / "default-repo"
SKILL = "templates/default-repo/.claude/skills/implement/SKILL.md"
CHANGE = "\nA line the working tree adds.\n"
CASE = "implement-refuses-dirty-tree"
REVIEW_CASE = "review-requirement-finds-the-gap"
# What the agent does when it implements the requirement despite the uncommitted change.
IMPLEMENTS_ANYWAY = {
    "commands": [
        "git switch -q -c feature-a",
        "touch feature-a.out",
        "git add feature-a.out",
        "git commit -qm 'Add feature-a.out'",
    ],
    "reply": "Implemented feature-a.md on feature-a.",
}
STOPS = {
    "commands": ["git status --porcelain --branch --untracked-files=all"],
    "reply": "notes.md has a change feature-a.md doesn't explain, so I changed nothing.",
}
SAVES_THE_REVIEW = (
    "printf '%s\\n' '## Summary' 'AC 1 allows 100 users a file, but AC 3 imports 500 at once.'"
    " | .claude/skills/review-requirement/save-review.sh specs/changes/todo/import-users.md no 1"
)


@pytest.fixture
def fake_claude() -> FakeClaude:
    """Stands in for Claude Code, signed in with a subscription (tests/fakes)."""
    directory = Path(os.environ["HOME"]) / ".fake-claude"
    directory.mkdir()
    return FakeClaude(directory)


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The system's temp folder as the eval sees it, holding what a past eval and others left."""
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    (folder / "repocop-eval-past").mkdir()
    (folder / "other").mkdir()
    (folder / "repocop-eval-link").symlink_to(folder / "other")
    return folder


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout with the repo template committed, and a change to its implement skill in the
    working tree."""
    root = tmp_path / "checkout"
    ignored = shutil.ignore_patterns("*Zone.Identifier")
    shutil.copytree(TEMPLATE, root / "templates" / "default-repo", ignore=ignored)
    run_git("init", "-q", "-b", "main", cwd=root)
    run_git("add", "--all", cwd=root)
    run_git("commit", "-qm", "Add the template", cwd=root)
    (root / SKILL).write_text((root / SKILL).read_text() + CHANGE)
    return root


def checkout_state(root: Path) -> tuple[str, str, str, int]:
    return (
        run_git("rev-parse", "HEAD", cwd=root),
        run_git("for-each-ref", cwd=root),
        run_git("status", "--porcelain", "--untracked-files=all", cwd=root),
        (root / ".git" / "index").stat().st_mtime_ns,
    )


def summary_of(results: Path) -> tuple[Path, str]:
    (summary,) = results.glob("*/summary.md")
    return summary, summary.read_text()


def test_eval_compares_the_sides_in_isolated_runs_and_leaves_the_checkout_as_it_was(
    checkout: Path,
    temp: Path,
    tmp_path: Path,
    fake_claude: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-the-developers")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    fake_claude.plan(IMPLEMENTS_ANYWAY, STOPS)
    results = tmp_path / "results"
    found = checkout_state(checkout)

    code = run_eval(
        ["--before", "HEAD", "--case", CASE, "--runs", "1", "--model", "opus", "--effort", "low"],
        root=checkout,
        results=results,
    )

    assert code == 0  # the after side passes
    assert checkout_state(checkout) == found
    assert "The eval makes 2 runs" in capsys.readouterr().out
    left = {p.name for p in temp.iterdir()}
    assert "repocop-eval-past" not in left  # the past eval's folder alone is gone
    assert {"other", "repocop-eval-link"} <= left and (temp / "other").is_dir()

    before, after = fake_claude.sessions
    allowed = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["permissions"][
        "allow"
    ]
    for session in (before, after):
        args, env, cwd = session["args"], session["env"], Path(session["cwd"])
        assert session["input"] == "/implement specs/changes/todo/feature-a.md\n"
        assert {"--strict-mcp-config", "--no-session-persistence", "--include-hook-events"} <= set(
            args
        )
        for option, value in (
            ("--setting-sources", "project"),
            ("--permission-mode", "auto"),
            ("--permission-prompts", "none"),
        ):
            assert args[args.index(option) + 1] == value
        assert json.loads(args[args.index("--settings") + 1]) == {"permissions": {"allow": allowed}}
        assert (
            args[args.index("--model") + 1] == "opus" and args[args.index("--effort") + 1] == "low"
        )
        assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "FAKE_GH_DIR"} & set(env)
        assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
        assert Path(env["GIT_CONFIG_GLOBAL"]) == cwd.parent / "gitconfig"
        assert cwd.name == CASE and cwd.parent.parent == temp
        assert (
            cwd.parent.name.startswith("repocop-eval-")
            and cwd.parent.stat().st_mode & 0o777 == 0o700
        )
    repo = Path(after["cwd"])
    assert run_git("log", "--format=%s", "main", cwd=repo) == "Initial commit"
    assert run_git("rev-parse", "--abbrev-ref", "origin/HEAD", cwd=repo) == "origin/main"
    assert run_git("ls-tree", "main", "--", ".claude/hooks/session-events.sh", cwd=repo).startswith(
        "100755"
    )
    assert run_git("status", "--porcelain", cwd=repo) == "M notes.md"  # its setup's change
    assert CASE in (repo / "CLAUDE.md").read_text()
    assert (repo / ".claude/skills/implement/SKILL.md").read_text().endswith(CHANGE)
    assert (
        not (Path(before["cwd"]) / ".claude/skills/implement/SKILL.md").read_text().endswith(CHANGE)
    )

    summary, text = summary_of(results)
    assert "- **Before:** HEAD at " in text
    assert "- **After:** the working tree, uncommitted changes included" in text
    assert "**Model:** claude-opus-5-5 · **Effort:** low · **Claude Code:** 2.1.282" in text
    assert "same" not in text
    for row in (
        "| **Case passes** | no | yes |",
        "| Passed | 0 of 1 | 1 of 1 |",
        "| Invalid | 0 | 0 |",
        "| Agent steps (median) | 5 | 2 |",
        "| Tokens, cache reads (median) | 200 | 80 |",
        "| first shell command was git status | 0 of 1 | 1 of 1 |",
    ):
        assert row in text
    assert "| before 1 | failed: pass check: the run changed the repository: " in text
    assert "| after 1 | passed |" in text
    for link in re.findall(r"\]\(([^)]+)\)", text):
        assert (summary.parent / link).is_file()


def test_eval_marks_runs_invalid_and_fails_when_a_case_fails_on_the_after_side(
    checkout: Path, temp: Path, tmp_path: Path, fake_claude: FakeClaude
) -> None:
    developers = Path(os.environ["HOME"]) / ".claude" / "skills" / "my-skill"
    developers.mkdir(parents=True)
    (developers / "SKILL.md").write_text("---\nname: my-skill\n---\n")
    fake_claude.plan(
        {
            "commands": [SAVES_THE_REVIEW],
            "skills": ["my-skill"],
            "mcp_servers": ["gmail"],
            "hooks": ["SessionStart", "PreCompact"],
        },
        {"commands": [SAVES_THE_REVIEW]},
        {"api_error_status": 529, "reply": "API Error: 529 Overloaded"},
        {"commands": [SAVES_THE_REVIEW], "model": "claude-sonnet-5-5"},
        {"commands": [SAVES_THE_REVIEW], "error": "error_during_execution"},
        {"commands": [SAVES_THE_REVIEW]},
    )
    results = tmp_path / "results"

    code = run_eval(
        ["--before", "HEAD", "--after", "HEAD", "--case", REVIEW_CASE, "--runs", "3"],
        root=checkout,
        results=results,
    )

    assert code == 1
    _, text = summary_of(results)
    assert "Both sides' templates are the same" in text
    for row in (
        "| **Case passes** | no | no |",
        "| Passed | 0 of 3 | 2 of 3 |",
        "| Invalid | 2 | 1 |",
    ):
        assert row in text
    assert (
        "| before 1 | invalid: loaded the developer's own "
        "MCP server gmail, hook on PreCompact, skill my-skill |" in text
    )
    assert "| after 1 | passed |" in text
    assert "| before 2 | invalid: the service failed the run (HTTP 529) |" in text
    assert "| after 2 | invalid: ran on claude-sonnet-5-5, not claude-opus-5-5 |" in text
    assert "| before 3 | failed: ended in an error: error_during_execution |" in text


@pytest.mark.parametrize(
    ("refusal", "says"),
    [
        ("not installed", "Claude Code isn't installed"),
        ("too old", "Claude Code 2.1.282 lacks --permission-prompts"),
        ("signed out", "isn't signed in with a Claude subscription"),
        ("signed in with a key", "isn't signed in with a Claude subscription"),
        ("instructions above", "CLAUDE.md is above the folder runs go in"),
        ("another eval running", "another eval is running"),
    ],
)
def test_eval_refuses_saying_why_and_runs_nothing(
    refusal: str,
    says: str,
    checkout: Path,
    temp: Path,
    tmp_path: Path,
    fake_claude: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = tmp_path / "results"
    results.mkdir()
    lock = (results / ".lock").open("w")
    if refusal == "not installed":
        only_git = tmp_path / "bin"
        only_git.mkdir()
        (only_git / "git").symlink_to(shutil.which("git") or "git")
        monkeypatch.setenv("PATH", str(only_git))
    elif refusal == "too old":
        fake_claude.lack("--permission-prompts")
    elif refusal == "signed out":
        fake_claude.answer_auth({"loggedIn": False})
    elif refusal == "signed in with a key":
        fake_claude.answer_auth({"loggedIn": True, "authMethod": "console"})
    elif refusal == "instructions above":
        (tmp_path / "CLAUDE.md").write_text("# Mine\n")
    else:
        fcntl.flock(lock, fcntl.LOCK_EX)

    code = run_eval(["--before", "HEAD"], root=checkout, results=results)

    assert code == 2
    assert says in capsys.readouterr().err
    assert fake_claude.sessions == []
    assert (temp / "repocop-eval-past").is_dir()  # nothing removed
    assert [p.name for p in results.iterdir()] == [".lock"]
    lock.close()
