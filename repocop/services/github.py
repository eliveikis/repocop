"""GitHub: the only module that runs `gh`, the GitHub CLI (ADR-023).

Every call is an argv list with an explicit working directory and a timeout. `gh` never prompts:
stdin is closed and its prompts are off, so a missing login fails with its own message instead
of hanging. Only repositories on github.com are served. `gh` is found on `PATH`, and uses the
login `gh auth login` stored.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from repocop.errors import RepoCopError
from repocop.services import git

GH = "gh"
HOST = "github.com"
TIMEOUT_S = 60.0


class GitHubError(RepoCopError):
    """GitHub can't be used as asked: the remote isn't there, or a `gh` command failed."""


def repository_of(remote_url: str) -> str:
    """`owner/name` of the github.com repository a remote URL names. Any other remote is refused."""
    page = git.web_url(remote_url) or ""
    match = re.fullmatch(rf"https://{re.escape(HOST)}/([^/]+/[^/]+)", page, re.IGNORECASE)
    if match is None:
        raise GitHubError(f"{remote_url} isn't a repository on {HOST}, so it has no pull requests")
    return match[1]


def check_ready(cwd: Path) -> None:
    """Refuse unless `gh` is installed and logged in to github.com."""
    if shutil.which(GH) is None:
        raise GitHubError(f"the GitHub CLI ({GH}) isn't installed, or isn't on PATH")
    try:
        _run(["auth", "status", "--hostname", HOST], cwd=cwd)
    except GitHubError:
        raise GitHubError(
            f"the GitHub CLI isn't logged in to {HOST}: run `gh auth login`"
        ) from None


def pull_request_of(cwd: Path, repository: str, branch: str) -> str | None:
    """The address of the open pull request from `branch`, or None when it has none."""
    listing = ["pr", "list", "--repo", repository, "--head", branch]
    found = json.loads(
        _run([*listing, "--state", "open", "--json", "url", "--limit", "1"], cwd=cwd)
    )
    return _pull_request_url(found[0]["url"]) if found else None


def create_pull_request(
    cwd: Path, repository: str, *, head: str, base: str, title: str, body: str
) -> str:
    """Open a pull request from `head`, which the remote must already have, into `base`. Returns
    its address. It is ready for review, not a draft."""
    branches = ["--repo", repository, "--head", head, "--base", base]
    output = _run(["pr", "create", *branches, "--title", title, "--body", body], cwd=cwd)
    return _pull_request_url(output.splitlines()[-1] if output else "")


def request_copilot_review(cwd: Path, pull_request: str) -> None:
    """Ask Copilot to review the pull request at this address, again if it already has."""
    _run(["pr", "edit", pull_request, "--add-reviewer", "@copilot"], cwd=cwd)


def _pull_request_url(text: str) -> str:
    """`text` if it is a pull request's address on github.com, so nothing else is ever linked."""
    if not re.fullmatch(rf"https://{re.escape(HOST)}/[\w.-]+/[\w.-]+/pull/\d+", text):
        raise GitHubError(f"gh didn't give the pull request's address, but: {text!r}")
    return text


def _run(args: list[str], *, cwd: Path) -> str:
    command = f"gh {' '.join(args[:2])}"
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"}
    try:
        result = subprocess.run(
            [GH, *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise GitHubError(f"{command} timed out after {TIMEOUT_S:g}s") from None
    except OSError as exc:
        raise GitHubError(f"{command} couldn't run: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise GitHubError(f"{command} failed: {detail}")
    return result.stdout.strip()
