"""Where an eval's runs happen: each side's repo template, read without touching the developer's
checkout, and each run's own repository, in a private folder under the system's temp folder.

The developer's checkout is only read: git runs there without optional locks, so even a status
doesn't rewrite its index, and nothing is checked out. A side's template is a snapshot taken
when the eval starts, at a ref with its files' modes as `git archive` gives them, or from the
working tree as git sees it, uncommitted and untracked files included but not ignored ones.

A run's repository is the case's own files with the side's template laid over them as a template
sync lays it out with every offered file picked (RepoCop's own `bootstrap`), all in one commit
on `main`, with a local `origin` beside it. Git there reads the run's own configuration, so
none of the developer's identity, signing or git hooks applies.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from evals.cases import Case
from evals.errors import EvalError
from repocop.errors import RepoCopError
from repocop.services import bootstrap
from repocop.services.bootstrap import FileState

TEMPLATE = "templates/default-repo"  # the repo template, in this repository
PREFIX = "repocop-eval-"  # every folder an eval makes in the temp folder starts with it
GIT_TIMEOUT_S = 60.0
# What a run's processes keep of the developer's environment: no variable that changes the
# model, the credential or what loads.
KEPT = ("PATH", "HOME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "USER", "LOGNAME")
RUN_GITCONFIG = """\
[user]
\tname = RepoCop eval
\temail = eval@repocop.invalid
[commit]
\tgpgSign = false
[tag]
\tgpgSign = false
[init]
\tdefaultBranch = main
"""
INSTRUCTIONS = ("CLAUDE.md", "CLAUDE.local.md", ".claude")  # what Claude Code loads from above


@dataclass(frozen=True)
class Side:
    name: str  # before or after
    label: str  # where its template came from
    template: Path  # the snapshot of its template's files


def git(cwd: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    """Run git in `cwd` and return its output; refused with git's own message if it fails."""
    return _git_bytes(cwd, list(args), env).decode("utf-8", "replace").strip()


def checkout_env() -> dict[str, str]:
    """The environment git runs with in the developer's checkout: theirs, but never prompting
    and taking no optional locks."""
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def run_env(folder: Path | None) -> dict[str, str]:
    """The environment of a run's processes: only what a run needs of the developer's, with
    Claude Code's memory, claude.ai connectors and updates off, and git reading the run's own
    configuration in its private `folder`, or none without one."""
    kept = {name: os.environ[name] for name in KEPT if name in os.environ}
    return {
        **kept,
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
        "DISABLE_AUTOUPDATER": "1",
        "GIT_CONFIG_GLOBAL": str(folder / "gitconfig") if folder else os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def resolve(root: Path, ref: str) -> str:
    """The commit `ref` names in the developer's checkout; refused when it names none."""
    if not ref or ref.startswith("-") or any(c.isspace() for c in ref):
        raise EvalError(f"{ref!r} isn't a ref")
    try:
        return git(
            root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", env=checkout_env()
        )
    except EvalError:
        raise EvalError(f"{ref} isn't a commit in {root}") from None


def default_branch(root: Path) -> str:
    """The default branch on `origin`, as last fetched, as `origin/<branch>`."""
    try:
        return git(root, "rev-parse", "--abbrev-ref", "origin/HEAD", env=checkout_env())
    except EvalError:
        raise EvalError(
            f"{root} doesn't know origin's default branch: run `git remote set-head origin "
            "--auto`, or name the before side with --before"
        ) from None


def snapshot_at(root: Path, commit: str, dest: Path) -> Path:
    """The template as committed at `commit`, with its files' modes, extracted under `dest`."""
    archive = _git_bytes(root, ["archive", "--format=tar", commit, "--", TEMPLATE], checkout_env())
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    return dest / TEMPLATE


def snapshot_working_tree(root: Path, dest: Path) -> Path:
    """The template in the working tree as git sees it, untracked files included and ignored
    ones left out, copied with their modes under `dest`."""
    listed = _git_bytes(
        root,
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", TEMPLATE],
        checkout_env(),
    )
    for name in sorted({name for name in listed.decode("utf-8").split("\0") if name}):
        source, target = root / name, dest / name
        if source.is_file() or source.is_symlink():  # a file deleted in the working tree is gone
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
    return dest / TEMPLATE


def same_templates(first: Path, second: Path) -> bool:
    """Whether two template snapshots have the same files, contents and executable bits."""
    return _contents(first) == _contents(second)


def private_folder() -> Path:
    """A new folder only this user can open, under the system's temp folder."""
    return Path(tempfile.mkdtemp(prefix=PREFIX)).resolve()


def remove_past() -> list[Path]:
    """Remove the folders past evals left in the temp folder, and nothing else: only this user's
    folders named as an eval names them, never through a link."""
    removed = []
    for path in sorted(Path(tempfile.gettempdir()).glob(f"{PREFIX}*")):
        if path.is_dir() and not path.is_symlink() and path.stat().st_uid == os.getuid():
            shutil.rmtree(path)
            removed.append(path)
    return removed


def check_temp_folder(root: Path) -> Path:
    """The temp folder runs go in, refused when it is in the developer's checkout or home folder,
    or when a folder above it holds instructions Claude Code would load into every run."""
    temp = Path(tempfile.gettempdir()).resolve()
    for owner, what in ((root.resolve(), "checkout"), (Path.home().resolve(), "home folder")):
        if temp.is_relative_to(owner):
            raise EvalError(
                f"the temp folder, {temp}, is in the developer's {what}: point TMPDIR elsewhere"
            )
    for folder in (temp, *temp.parents):
        for name in INSTRUCTIONS:
            if (found := folder / name).exists():
                raise EvalError(
                    f"{found} is above the folder runs go in, {temp}, and Claude Code would load "
                    "it into every run: move it, or point TMPDIR at a folder with none above it"
                )
    return temp


def build(folder: Path, case: Case, side: Side) -> Path:
    """The run's repository in `folder`, named after the case: the case's files with the side's
    template laid over them, as one commit on `main`, with a local `origin` beside it whose
    default branch is `main`. Git there reads the configuration `run_env` names."""
    (folder / "gitconfig").write_text(RUN_GITCONFIG, encoding="utf-8")
    env = run_env(folder)
    repo = folder / case.name
    if case.files is not None:
        shutil.copytree(case.files, repo, symlinks=True)
    repo.mkdir(exist_ok=True)
    git(repo, "init", "--quiet", "--template=", "--initial-branch=main", env=env)
    git(repo, "add", "--all", env=env)
    git(repo, "commit", "--quiet", "--allow-empty", "--message", "Initial commit", env=env)
    try:
        plan = bootstrap.sync_plan(side.template, repo, "HEAD", case.name)
        for file in plan.offered:
            target = repo / file.path
            if file.state is FileState.RETIRED:
                target.unlink()
            elif file.state is FileState.BEHIND:
                current = target.read_bytes()
                target.write_bytes(bootstrap.merge(side.template, file.path, case.name, current))
            else:
                bootstrap.write(side.template, repo, file.path, case.name)
    except RepoCopError as exc:
        raise EvalError(f"the {side.name} side's template can't be laid out: {exc}") from exc
    git(repo, "add", "--all", env=env)
    git(repo, "commit", "--quiet", "--amend", "--allow-empty", "--no-edit", env=env)
    origin = folder / "origin.git"
    git(
        folder,
        "init",
        "--quiet",
        "--bare",
        "--template=",
        "--initial-branch=main",
        str(origin),
        env=env,
    )
    git(repo, "remote", "add", "origin", str(origin), env=env)
    git(repo, "push", "--quiet", "--set-upstream", "origin", "main", env=env)
    git(repo, "remote", "set-head", "origin", "main", env=env)
    return repo


def state(repo: Path, env: Mapping[str, str]) -> str:
    """A record of the repository's final state: its branches, their commits and what's
    uncommitted."""
    sections = {
        "Branches": ["branch", "--list", "--verbose", "--no-abbrev"],
        "Commits": ["log", "--branches", "--graph", "--decorate", "--format=%h%d %s"],
        "Files each later commit changed": [
            "log",
            "--branches",
            "--min-parents=1",
            "--format=%h %s",
            "--name-status",
        ],
        "Uncommitted": ["status", "--short", "--branch", "--untracked-files=all"],
        "Uncommitted changes": ["diff", "HEAD"],
    }
    return "".join(
        f"## {title}\n\n{git(repo, *args, env=env)}\n\n" for title, args in sections.items()
    )


def _git_bytes(cwd: Path, args: list[str], env: Mapping[str, str] | None) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise EvalError(f"git {args[0]} timed out after {GIT_TIMEOUT_S:g}s in {cwd}") from None
    if result.returncode != 0:
        detail = (
            result.stderr.decode("utf-8", "replace").strip() or f"exit code {result.returncode}"
        )
        raise EvalError(f"git {args[0]} failed in {cwd}: {detail}")
    return result.stdout


def _contents(template: Path) -> dict[str, tuple[bytes, bool]]:
    return {
        path.relative_to(template).as_posix(): (path.read_bytes(), os.access(path, os.X_OK))
        for path in sorted(template.rglob("*"))
        if path.is_file()
    }
