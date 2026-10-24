"""Shared fixtures.

Tests must never touch the real ~/code, ~/agent-worktrees, or RepoCop's real database.
Everything lives under pytest's tmp_path, and git identity is pinned so commits work on CI.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import signal
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repocop import db
from repocop.config import FORMER_NAME, Settings
from repocop.main import create_app
from repocop.services import bootstrap, claude
from tests.fakes.fake_claude import FakeClaudeFactory
from tests.fakes.fake_codex import FakeCodex
from tests.fakes.fake_gh import FakeGh

FAKE_CLAUDE_CLI = Path(__file__).parent / "fakes" / "claude-cli"
# First on PATH in every test: holds `gh` and `codex`.
FAKE_BIN = Path(__file__).parent / "fakes" / "bin"


def run_git(*args: str, cwd: Path) -> str:
    """Run git with an argv list (never a shell string) and return stdout."""
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def write_template(template_dir: Path, checkout: Path, repo_name: str = "sample") -> None:
    """Write every file of the repo template into `checkout`, rendered as a sync writes it."""
    for path in bootstrap.kinds(template_dir):
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bootstrap.rendered(template_dir, path, repo_name))


def process_gone(pid: int | None, timeout: float = 5.0) -> bool:
    """Whether the process has ended within `timeout` (a zombie waiting to be reaped counts)."""
    assert pid is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


def kill_process(pid: int | None) -> None:
    if pid is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def push_commit(remote: Path, workdir: Path, name: str = "upstream.txt") -> str:
    """Add a commit to `remote`'s `main` from a clone under `workdir`, and return its hash."""
    clone = workdir / "pusher"
    if not clone.exists():
        run_git("clone", "-q", str(remote), str(clone), cwd=workdir)
    (clone / name).write_text("from upstream\n")
    run_git("add", name, cwd=clone)
    run_git("commit", "-qm", f"Add {name}", cwd=clone)
    run_git("push", "-q", "origin", "main", cwd=clone)
    return run_git("rev-parse", "HEAD", cwd=clone)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep git, GitHub and RepoCop config hermetic for every test.

    The working directory moves to tmp_path too, so a real ./repocop.yaml can't leak in.
    `gh` and `codex` are the fakes, each of which fails unless the test asked for it with its
    fixture, `fake_gh` or `fake_codex`.
    """
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("FAKE_GH_DIR", raising=False)
    monkeypatch.delenv("FAKE_CODEX_DIR", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    for key in list(os.environ):
        if key.startswith(("REPOCOP_", f"{FORMER_NAME.upper()}_", "ANTHROPIC_")):
            monkeypatch.delenv(key)


@dataclass(frozen=True)
class HostLayout:
    """A throwaway host: where repos, worktrees and state live."""

    root: Path
    repos_root: Path
    worktrees_root: Path
    data_dir: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / "repocop.db"


@pytest.fixture
def host(tmp_path: Path) -> HostLayout:
    layout = HostLayout(
        root=tmp_path,
        repos_root=tmp_path / "code",
        worktrees_root=tmp_path / "agent-worktrees",
        data_dir=tmp_path / "data",
    )
    for p in (layout.repos_root, layout.worktrees_root, layout.data_dir):
        p.mkdir(parents=True)
    return layout


@pytest.fixture
def template_dir(tmp_path: Path) -> Path:
    """A small repo template: a placeholder, a script, a binary file, and a kept empty directory."""
    root = tmp_path / "template"
    (root / ".claude" / "skills" / "demo").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("# {{ repo_name }}\n")
    script = root / ".claude" / "skills" / "demo" / "run.sh"
    script.write_text("#!/bin/sh\necho demo\n")
    script.chmod(0o755)
    (root / "logo.bin").write_bytes(b"\x89\xff{{ repo_name }}")
    (root / "specs" / "changes" / "todo").mkdir(parents=True)
    (root / "specs" / "changes" / "todo" / ".gitkeep").write_text("")
    return root


TEMPLATE_SETTINGS = {
    "permissions": {"allow": ["Bash(make check)"], "ask": ["Bash(git push:*)"]},
    "model": "sonnet",
}


@pytest.fixture
def declared_kinds(template_dir: Path) -> Path:
    """The small template with CLAUDE.md as a starter file and `.claude/settings.json` merged."""
    (template_dir / ".claude" / "settings.json").write_text(json.dumps(TEMPLATE_SETTINGS) + "\n")
    (template_dir / bootstrap.MANIFEST).write_text(
        'starter = ["CLAUDE.md"]\nmerged = [".claude/settings.json"]\n'
    )
    return template_dir


@pytest.fixture
def settings(host: HostLayout, template_dir: Path) -> Settings:
    """Settings pointing at the throwaway host layout and the small template."""
    return Settings(
        repos_root=host.repos_root,
        worktrees_root=host.worktrees_root,
        database_path=host.database_path,
        logs_dir=host.data_dir / "logs",
        template_dir=template_dir,
        claude_bin=str(FAKE_CLAUDE_CLI),
    )


@pytest.fixture(autouse=True)
def _no_real_claude(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any use of the real SDK client fail, except in tests marked `claude`."""
    if "claude" in request.keywords:
        return

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "the default test suite never calls Claude; use the fake_claude fixture"
        )

    monkeypatch.setattr(claude, "ClaudeSDKClient", refuse)


@pytest.fixture
def fake_claude() -> FakeClaudeFactory:
    """Stands in for the Claude SDK client; keeps every session it made (tests/fakes)."""
    return FakeClaudeFactory()


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    """Stands in for the GitHub CLI: logged in, with no pull requests (tests/fakes)."""
    directory = tmp_path / "gh"
    directory.mkdir()
    monkeypatch.setenv("FAKE_GH_DIR", str(directory))
    return FakeGh(directory)


@pytest.fixture
def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCodex:
    """Stands in for the Codex CLI: signed in, and its reviews find nothing (tests/fakes)."""
    directory = tmp_path / "codex"
    directory.mkdir()
    monkeypatch.setenv("FAKE_CODEX_DIR", str(directory))
    return FakeCodex(directory)


@pytest.fixture
def git_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], list[list[str]]]:
    """Records every `git` run from here on. Call it for their arguments so far, in order."""
    real, folder, log = shutil.which("git"), tmp_path / "recording-git", tmp_path / "git-calls"
    folder.mkdir()
    wrapper = folder / "git"
    wrapper.write_text(
        f'#!/bin/sh\nIFS=$(printf "\\037")\nprintf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
        f'exec {shlex.quote(str(real))} "$@"\n'
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    return lambda: [line.split("\x1f") for line in log.read_text().splitlines()]


@pytest.fixture
def client(settings: Settings, fake_claude: FakeClaudeFactory) -> Iterator[TestClient]:
    """The app on the throwaway host, started (database migrated), with Claude faked."""
    with TestClient(create_app(settings, claude_client=fake_claude)) as test_client:
        yield test_client


@pytest.fixture
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    """A connection to a migrated RepoCop database under the throwaway host."""
    connection = db.connect(settings.database_path)
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def remote_repo(tmp_path: Path) -> Path:
    """A bare repo with one commit on `main` — usable as a clone URL (file path)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    run_git("init", "-q", "-b", "main", cwd=seed)
    (seed / "README.md").write_text("# sample\n")
    run_git("add", ".", cwd=seed)
    run_git("commit", "-q", "-m", "initial", cwd=seed)

    bare = tmp_path / "remotes" / "sample.git"
    bare.parent.mkdir()
    run_git("clone", "-q", "--bare", str(seed), str(bare), cwd=tmp_path)
    shutil.rmtree(seed)
    return bare


@pytest.fixture
def primary_checkout(host: HostLayout, remote_repo: Path) -> Iterator[Path]:
    """A human-owned primary checkout cloned from `remote_repo` under repos_root."""
    dest = host.repos_root / "sample"
    run_git("clone", "-q", str(remote_repo), str(dest), cwd=host.repos_root)
    yield dest


GITHUB_REMOTE = "git@github.com:owner/sample.git"


@pytest.fixture
def github_checkout(
    primary_checkout: Path, remote_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The primary checkout with `origin` on github.com. An ssh stand-in runs what git asks of
    that host on `remote_repo` instead, so pushes land there and no test reaches the network."""
    ssh = tmp_path / "github-ssh" / "ssh"
    ssh.parent.mkdir()
    ssh.write_text(
        "#!/bin/sh\n"
        "for asked; do :; done\n"  # git's last argument, e.g. git-receive-pack 'owner/sample.git'
        "service=${asked%% *}\n"
        f'exec git "${{service#git-}}" {shlex.quote(str(remote_repo))}\n'
    )
    ssh.chmod(0o755)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(ssh))
    run_git("remote", "set-url", "origin", GITHUB_REMOTE, cwd=primary_checkout)
    return primary_checkout


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked `claude` unless REPOCOP_TEST_REAL_CLAUDE=1."""
    if os.environ.get("REPOCOP_TEST_REAL_CLAUDE") == "1":
        return
    skip = pytest.mark.skip(reason="set REPOCOP_TEST_REAL_CLAUDE=1 to run real-CLI tests")
    for item in items:
        if "claude" in item.keywords:
            item.add_marker(skip)
