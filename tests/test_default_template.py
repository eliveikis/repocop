"""The default repo template: its copies of this repo's shared files, and a complete sync."""

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from repocop.config import PROJECT_ROOT, Settings
from repocop.services import bootstrap, repositories, template_sync
from repocop.services.bootstrap import Kind
from repocop.services.repositories import Status
from tests.conftest import run_git

TEMPLATE = PROJECT_ROOT / "templates" / "default-repo"
# Shipped to onboarded repos as copies of this repo's own files, so edit both together.
MIRRORED = (
    ".claude/skills",
    ".claude/rules/principles.md",
    ".claude/rules/specs.md",
    ".claude/rules/skills.md",
    ".claude/rules/commits.md",
    ".claude/rules/reviews.md",
    ".claude/rules/test-policy.md",
    ".claude/hooks/linux-only-path.sh",
    ".claude/hooks/amend-only-unpushed.sh",
    ".claude/hooks/session-events.sh",
    ".reviews/.gitignore",
    ".reviews/review.sh",
    "specs/changes/README.md",
    "specs/changes/backlog.sh",
    "specs/changes/.gitignore",
)
# What a managed file carries, in Markdown and in files whose comments start with `#`.
MARKDOWN_MARKER = "<!-- managed by template -->"
COMMENT_MARKER = "# managed by template"
LINUX_ONLY_PATH = TEMPLATE / ".claude" / "hooks" / "linux-only-path.sh"
AMEND_ONLY_UNPUSHED = TEMPLATE / ".claude" / "hooks" / "amend-only-unpushed.sh"
SESSION_EVENTS = TEMPLATE / ".claude" / "hooks" / "session-events.sh"
# Each event the session hook records, with the matcher it runs on, if any.
SESSION_HOOK_RUNS_ON = {
    "SessionStart": None,
    "CwdChanged": None,
    "UserPromptSubmit": None,
    "UserPromptExpansion": None,
    "PreToolUse": "Skill|AskUserQuestion",
    "PermissionRequest": None,
    "Notification": "permission_prompt|elicitation_dialog",
    "PostToolUse": None,
    "Stop": None,
    "SessionEnd": None,
}
OSRELEASE = Path("/proc/sys/kernel/osrelease")
ON_WSL = OSRELEASE.is_file() and "microsoft" in OSRELEASE.read_text().lower()
# Real tools first, so the hook and the shell sourcing its output can run.
SAMPLE_PATH = "/usr/bin:/bin:/mnt/c/Windows/System32:/mnt/c/Program Files/Docker/bin:/mnt/data/bin"


def files_under(root: Path, relative: str) -> dict[str, tuple[bytes, bool]]:
    """Content and executable bit of every file at `root/relative`, keyed by path."""
    base = root / relative
    paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
    return {p.relative_to(root).as_posix(): (p.read_bytes(), os.access(p, os.X_OK)) for p in paths}


def run_linux_only_path(tmp_path: Path) -> tuple[str, str]:
    """What the hook tells Claude, and what it leaves for Bash commands to source."""
    env_file = tmp_path / "claude-env"
    env_file.touch()
    env = {"PATH": SAMPLE_PATH, "CLAUDE_ENV_FILE": str(env_file)}
    result = subprocess.run(
        [LINUX_ONLY_PATH], cwd=tmp_path, env=env, check=True, capture_output=True, text=True
    )
    return result.stdout, env_file.read_text()


@pytest.mark.parametrize("relative", MIRRORED)
def test_default_template_mirrors_this_repos_shared_files(relative: str) -> None:
    ours = files_under(PROJECT_ROOT, relative)
    shipped = files_under(TEMPLATE, relative)
    drifted = sorted(
        path for path in ours.keys() | shipped.keys() if ours.get(path) != shipped.get(path)
    )
    shipped_path = f"templates/default-repo/{relative}"
    assert drifted == [], (
        f"{shipped_path} differs from {relative} ({', '.join(drifted)}). Onboarded repos get "
        "the template's copy, so keep it repo-agnostic and copy it over: "
        f"rm -rf {shipped_path} && cp -a {relative} {shipped_path}"
    )


def test_default_template_uses_only_the_documented_placeholder() -> None:
    found = {
        placeholder
        for path in TEMPLATE.rglob("*")
        if path.is_file()
        for placeholder in re.findall(r"\{\{.*?\}\}", path.read_text(encoding="utf-8"))
    }
    assert found == {bootstrap.PLACEHOLDER}


def test_default_template_settings_are_valid_json() -> None:
    settings = json.loads((TEMPLATE / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"]


@pytest.mark.parametrize("root", [TEMPLATE, PROJECT_ROOT], ids=["template", "this repo"])
def test_settings_hide_claude_attribution(root: Path) -> None:
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["attribution"] == {"commit": "", "pr": ""}


def test_default_template_syncs_a_fresh_repository_until_it_is_ready(
    conn: sqlite3.Connection, settings: Settings, remote_repo: Path
) -> None:
    real = settings.model_copy(update={"template_dir": TEMPLATE})
    repo = repositories.register(conn, real, str(remote_repo), default_branch="main").repository
    missing = [file.path for file in repositories.template_plan(repo, real).missing]
    task = template_sync.apply(conn, real, repo, create=missing, overwrite=[])
    assert task is not None and task.branch is not None and task.worktree_path is not None
    pushed = f"{task.branch}:main"  # as a merged pull request would leave origin
    subprocess.run(["git", "push", "-q", "origin", pushed], cwd=repo.primary_path, check=True)
    assert repositories.status(repo, real) is Status.READY
    checkout = task.worktree_path
    assert "**sample**" in (checkout / "CLAUDE.md").read_text()
    assert "**sample**" in (checkout / "REVIEW.md").read_text()
    assert "follow [REVIEW.md](REVIEW.md)" in (checkout / "AGENTS.md").read_text()
    kept = subprocess.run(
        [
            "git",
            "check-ignore",
            ".reviews/my-branch.md",
            ".reviews/.gitignore",
            ".reviews/review.sh",
        ],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert kept.stdout.split() == [".reviews/my-branch.md"]  # a review is ignored, the rest isn't
    assert os.access(checkout / ".reviews" / "review.sh", os.X_OK)
    assert not (checkout / bootstrap.MANIFEST).exists()
    assert (checkout / "README.md").read_text() == "# sample\n"
    assert os.access(checkout / ".claude/skills/address-pr-comments/fetch-threads.sh", os.X_OK)


@pytest.mark.parametrize("skill", ["address-pr-comments", "address-review"])
def test_review_skills_report_their_one_commit_once(skill: str) -> None:
    report = (TEMPLATE / ".claude" / "skills" / skill / "SKILL.md").read_text()
    report = report[report.index("## Final report") :]
    assert "| Commit |" not in report
    assert report.count("Commit: ") == 1


def test_default_template_allowlist_covers_what_the_shipped_skills_run() -> None:
    permissions = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["permissions"]
    for command in (
        "git add",
        "git commit",
        "git mv",
        "git grep",
        "git merge-base",
        "git branch --show-current",
        "git rev-parse",
        "make check",
    ):
        assert any(rule.startswith(f"Bash({command}") for rule in permissions["allow"]), command
    assert "Bash(git push:*)" in permissions["ask"]
    for script in sorted((TEMPLATE / ".claude" / "skills").glob("*/*.sh")):
        rule = f"Bash({script.relative_to(TEMPLATE).as_posix()}:*)"
        assert rule in permissions["allow"], rule


def test_default_template_states_which_requirement_a_branch_belongs_to_once() -> None:
    claude = TEMPLATE / ".claude"
    stating = sorted(
        path.relative_to(claude).as_posix()
        for path in claude.rglob("*.md")
        if "belongs to a requirement when" in path.read_text(encoding="utf-8")
    )
    assert stating == ["rules/specs.md"]
    pointer = "`.claude/rules/specs.md` \u203a A branch's requirement"
    for path in (
        "rules/reviews.md",
        "skills/review-requirement/SKILL.md",
        "skills/implement/SKILL.md",
        "skills/address-review/SKILL.md",
        "skills/complete-change/SKILL.md",
    ):
        assert pointer in (claude / path).read_text(encoding="utf-8"), path


def test_default_template_settings_deny_windows_programs() -> None:
    deny = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    for program in ("cmd.exe", "powershell.exe", "pwsh.exe", "wsl.exe"):
        assert f"Bash({program} *)" in deny, program
    assert "Bash(/mnt/*)" in deny


def test_default_template_settings_deny_reading_env_files() -> None:
    deny = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert {"Read(./.env)", "Read(./.env.*)"} <= set(deny)


def test_default_template_settings_disable_bypass_permissions_mode() -> None:
    permissions = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["permissions"]
    assert permissions["disableBypassPermissionsMode"] == "disable"


def test_default_template_settings_run_linux_only_path_at_session_start() -> None:
    hooks = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["hooks"]
    commands = [hook["command"] for entry in hooks["SessionStart"] for hook in entry["hooks"]]
    assert '"$CLAUDE_PROJECT_DIR"/.claude/hooks/linux-only-path.sh' in commands
    assert os.access(LINUX_ONLY_PATH, os.X_OK)


@pytest.mark.parametrize("root", [TEMPLATE, PROJECT_ROOT], ids=["template", "this repo"])
def test_settings_record_each_session_event_without_waiting_on_it(root: Path) -> None:
    hooks = json.loads((root / ".claude" / "settings.json").read_text())["hooks"]
    command = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-events.sh'
    runs_on = {
        event: entry.get("matcher")
        for event, entries in hooks.items()
        for entry in entries
        for hook in entry["hooks"]
        if hook["command"] == command and hook.get("async") is True
    }
    assert runs_on == SESSION_HOOK_RUNS_ON
    assert os.access(SESSION_EVENTS, os.X_OK)


@pytest.mark.parametrize("root", [TEMPLATE, PROJECT_ROOT], ids=["template", "this repo"])
def test_settings_check_each_bash_command_for_an_amend_of_a_pushed_commit(root: Path) -> None:
    hooks = json.loads((root / ".claude" / "settings.json").read_text())["hooks"]
    commands = [
        hook["command"]
        for entry in hooks["PreToolUse"]
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
    ]
    assert '"$CLAUDE_PROJECT_DIR"/.claude/hooks/amend-only-unpushed.sh' in commands
    assert os.access(AMEND_ONLY_UNPUSHED, os.X_OK)


def run_amend_only_unpushed(
    checkout: Path, command: str, description: str = ""
) -> subprocess.CompletedProcess[str]:
    """The hook's answer to Claude running `command` in `checkout`."""
    tool_input = {"command": command, "description": description}
    payload = {"tool_name": "Bash", "tool_input": tool_input, "cwd": str(checkout)}
    return subprocess.run(
        [AMEND_ONLY_UNPUSHED], input=json.dumps(payload), capture_output=True, text=True
    )


def test_amend_only_unpushed_refuses_to_amend_a_pushed_commit(primary_checkout: Path) -> None:
    refused = run_amend_only_unpushed(primary_checkout, 'git commit --amend -m "Reworded"')
    assert refused.returncode == 2
    assert "already on origin/main" in refused.stderr
    assert "Make a new commit instead" in refused.stderr


def commit_unpushed(checkout: Path) -> None:
    (checkout / "notes.md").write_text("Not pushed.\n")
    run_git("add", "notes.md", cwd=checkout)
    run_git("commit", "-qm", "Add notes", cwd=checkout)


def test_amend_only_unpushed_lets_an_unpushed_commit_be_amended(primary_checkout: Path) -> None:
    commit_unpushed(primary_checkout)
    assert run_amend_only_unpushed(primary_checkout, "git commit --amend --no-edit").returncode == 0


@pytest.mark.parametrize(
    "command",
    [
        "git -C ../other commit --amend --no-edit",
        "cd ../other && git commit --amend --no-edit",
        "GIT_DIR=../other/.git git commit --amend --no-edit",
        "git --work-tree=../other commit --amend --no-edit",
        "set -e\ncd ../other\ngit commit --amend --no-edit",
    ],
)
def test_amend_only_unpushed_refuses_an_amend_aimed_at_another_checkout(
    primary_checkout: Path, command: str
) -> None:
    commit_unpushed(primary_checkout)  # so only where it points can be the reason
    refused = run_amend_only_unpushed(primary_checkout, command)
    assert refused.returncode == 2
    assert "can't tell which checkout it amends" in refused.stderr


def test_amend_only_unpushed_ignores_other_commands(primary_checkout: Path) -> None:
    allowed = run_amend_only_unpushed(primary_checkout, 'git commit -m "A new one"')
    assert (allowed.returncode, allowed.stderr) == (0, "")


def test_amend_only_unpushed_reads_only_the_command(primary_checkout: Path) -> None:
    allowed = run_amend_only_unpushed(
        primary_checkout, "git status", description="Check the branch before a commit --amend"
    )
    assert (allowed.returncode, allowed.stderr) == (0, "")


@pytest.mark.skipif(not ON_WSL, reason="the hook acts only on WSL")
def test_linux_only_path_drops_windows_drives_from_path_on_wsl(tmp_path: Path) -> None:
    told, _ = run_linux_only_path(tmp_path)
    sourced = subprocess.run(
        ["sh", "-c", '. "$1" && printf %s "$PATH"', "sh", tmp_path / "claude-env"],
        cwd=tmp_path,
        env={"PATH": SAMPLE_PATH},
        check=True,
        capture_output=True,
        text=True,
    )
    assert sourced.stdout == "/usr/bin:/bin:/mnt/data/bin"
    assert "Windows" in told


@pytest.mark.skipif(ON_WSL, reason="the hook acts on WSL")
def test_linux_only_path_changes_nothing_off_wsl(tmp_path: Path) -> None:
    assert run_linux_only_path(tmp_path) == ("", "")


def test_default_template_marks_its_managed_files_and_no_others() -> None:
    for path, kind in bootstrap.kinds(TEMPLATE).items():
        data = (TEMPLATE / path).read_bytes()
        assert bootstrap.has_marker(data) is (kind is Kind.MANAGED), path
        if kind is Kind.MANAGED:
            marker = MARKDOWN_MARKER if path.endswith(".md") else COMMENT_MARKER
            assert f"\n{marker}\n".encode() in b"\n" + data, path


def test_default_template_leaves_its_stubs_to_the_repository_and_merges_its_settings() -> None:
    kinds = bootstrap.kinds(TEMPLATE)
    starters = {path for path, kind in kinds.items() if kind is Kind.STARTER}
    assert starters == {
        "AGENTS.md",
        "CLAUDE.md",
        "REVIEW.md",
        "specs/index.md",
        "specs/product.md",
        "specs/architecture.md",
    }
    assert {path for path, kind in kinds.items() if kind is Kind.MERGED} == {
        ".claude/settings.json"
    }
