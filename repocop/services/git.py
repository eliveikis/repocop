"""Git: the only module that runs `git` (invariant 2).

Every call is an argv list with an explicit working directory, never a shell string. Git never
prompts: stdin is closed, terminal and credential-manager prompts are off, ssh runs in batch
mode, and every call has a timeout. A missing credential or unknown host key therefore fails
fast with git's own message instead of hanging. Commands that only read take no optional locks,
so they never rewrite a checkout's index.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, cast
from urllib.parse import unquote, urlsplit

from repocop.errors import RepoCopError

LOCAL_TIMEOUT_S = 60.0
MAX_NEW_FILES_IN_DIFF = 100
NETWORK_TIMEOUT_S = 600.0
TERMINATE_GRACE_S = 5.0

_USER = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
_PATH = r"[A-Za-z0-9._~%+/-]+"
_SCP = re.compile(rf"(?:{_USER})@(?P<host>{_HOST}):(?P<path>{_PATH})")
# `host` is where a browser finds the remote, so it keeps an https port and drops an ssh one.
_URL_FORMS = (
    re.compile(rf"https://(?:{_USER}@)?(?P<host>{_HOST}(?::\d+)?)/(?P<path>{_PATH})"),
    re.compile(rf"ssh://(?:{_USER}@)?(?P<host>{_HOST})(?::\d+)?/(?P<path>{_PATH})"),
    _SCP,
)
# Every branch on origin, to its remote-tracking branch. An empty --refmap goes with it, or git
# also applies the checkout's configured refspecs to what it fetches.
_TRACKING_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"
# Files git keeps while an operation is half done, and the operation each one means.
_UNFINISHED = (
    ("MERGE_HEAD", "merge"),
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
)
# In `git status --porcelain=v2`, how many fields come before the path in each kind of entry.
_FIELDS_BEFORE_PATH = {"1": 7, "2": 8, "u": 9}
SUPPORTED_FORMS = (
    "https://, ssh://, git@host:owner/repo, file:///path, or an existing absolute path"
)


class GitError(RepoCopError):
    """A git command failed or timed out, or a remote URL isn't supported."""


def check_remote_url(url: str) -> str:
    """Return `url` if it is a supported, safe remote URL (`.claude/rules/safety.md`)."""
    if not url:
        raise GitError("the remote URL is empty")
    safe_chars = not url.startswith("-") and all(c.isprintable() and not c.isspace() for c in url)
    if safe_chars:
        if any(form.fullmatch(url) for form in _URL_FORMS):
            return url
        if url.startswith("file:///"):
            return url
        if not url.startswith("file:") and Path(url).is_absolute() and Path(url).exists():
            return url
    raise GitError(f"unsupported remote URL {url!r}: use {SUPPORTED_FORMS}")


def remote_identity(url: str) -> str:
    """A key that is equal for every spelling of the same remote.

    Scheme, user, port, host case, surrounding slashes and a `.git` suffix don't matter. Local
    paths and `file://` URLs compare by resolved path, with `file://` percent-escapes decoded as
    git decodes them.
    """
    if scp := _SCP.fullmatch(url):
        host, path = scp["host"], scp["path"]
    elif url.startswith(("https://", "ssh://")):
        parts = urlsplit(url)
        host, path = parts.hostname or "", parts.path
    else:
        local = unquote(url.removeprefix("file://")) if url.startswith("file://") else url
        host, path = "", str(Path(local).resolve())
    return f"{host.lower()}/{path.strip('/').removesuffix('.git')}"


def web_url(url: str) -> str | None:
    """The remote repository's address in a browser, or None when the remote isn't on a host.

    It is `https://<host>/<path>` without the user and the `.git` suffix: the repository's page
    on GitHub and on hosts laid out like it.
    """
    for form in _URL_FORMS:
        if match := form.fullmatch(url):
            return f"https://{match['host']}/{match['path'].strip('/').removesuffix('.git')}"
    return None


def clone(url: str, dest: Path, *, timeout: float = NETWORK_TIMEOUT_S) -> None:
    """Clone `url` into `dest`, which must not exist yet. Git removes `dest` if the clone fails."""
    check_remote_url(url)
    _run(["clone", "--quiet", "--", url, str(dest)], cwd=dest.parent, timeout=timeout, network=True)


def fetch(path: Path, *, timeout: float = NETWORK_TIMEOUT_S) -> None:
    """Update the checkout's remote-tracking branches from `origin`, and nothing else.

    No tags are fetched, nothing is pruned, and submodules are left alone, so the working tree,
    index, HEAD, local branches and tags stay as they were. The refspecs the checkout configures
    for `origin` are ignored, so they can't send what's fetched anywhere else.
    """
    origin = remote_url(path)
    if origin is None:
        raise GitError(f"{path} has no origin remote to fetch from")
    check_remote_url(origin)
    options = ["--quiet", "--no-tags", "--no-prune", "--no-recurse-submodules", "--refmap="]
    args = ["fetch", *options, "origin", _TRACKING_REFSPEC]
    _run(args, cwd=path, timeout=timeout, network=True)


def push(path: Path, branch: str, *, timeout: float = NETWORK_TIMEOUT_S) -> None:
    """Send `branch` to `origin` under the same name, and make that its upstream.

    Never forced: when the remote branch has commits `branch` lacks, it is left as it is and the
    push is refused. Only that branch is sent, with no tags and no submodules, whatever the
    checkout's push settings say.
    """
    push_urls(path)
    ref = f"refs/heads/{branch}"
    options = ["--quiet", "--set-upstream", "--no-follow-tags", "--no-recurse-submodules"]
    try:
        _run(["push", *options, "origin", f"{ref}:{ref}"], cwd=path, timeout=timeout, network=True)
    except GitError as exc:
        if "[rejected]" not in str(exc):  # git's own word for a push that would need forcing
            raise
        raise GitError(
            f"origin's {branch} has commits this branch doesn't, so nothing was pushed. "
            "Bring them into the worktree first: RepoCop never forces a push."
        ) from None


def push_urls(path: Path) -> list[str]:
    """Where a push to `origin` goes: every URL git would send it to, after the checkout's
    `pushurl` and URL rewrites. Refused unless each is a supported, safe remote URL."""
    urls = _run(["remote", "get-url", "--push", "--all", "origin"], cwd=path).splitlines()
    for url in urls:
        check_remote_url(url)
    return urls


def is_checkout(path: Path) -> bool:
    """True if `path` is the top level of a git working tree."""
    if not path.is_dir():
        return False
    try:
        top = _run(["rev-parse", "--show-toplevel"], cwd=path)
    except GitError:
        return False
    return Path(top).resolve() == path.resolve()


def common_dir(path: Path) -> Path:
    """The repository folder a checkout belongs to, shared by all of its worktrees."""
    return Path(
        _run(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=path)
    ).resolve()


def remote_url(path: Path) -> str | None:
    """The URL of the checkout's `origin` remote, or None if it has none."""
    try:
        return _run(["remote", "get-url", "origin"], cwd=path) or None
    except GitError:
        return None


def default_branch(path: Path) -> str:
    """The branch `origin/HEAD` points to, or else the checked-out branch."""
    with contextlib.suppress(GitError):
        ref = _run(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd=path)
        return ref.removeprefix("origin/")
    branch = _run(["branch", "--show-current"], cwd=path)
    if not branch:
        raise GitError(
            f"can't tell the default branch of {path}: HEAD is detached and origin/HEAD is unset"
        )
    return branch


def current_branch(path: Path) -> str | None:
    """The checked-out branch, or None on a detached HEAD."""
    try:
        return _run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=path)
    except GitError:
        return None


def unfinished_operation(path: Path) -> str | None:
    """The merge, rebase, cherry-pick or revert left half done in the checkout, if any."""
    args = ["rev-parse"]
    for marker, _ in _UNFINISHED:
        args += ["--git-path", marker]
    markers = _run(args, cwd=path).splitlines()
    for marker_path, (_, operation) in zip(markers, _UNFINISHED, strict=True):
        if (path / marker_path).exists():
            return operation
    return None


@dataclass(frozen=True)
class CheckoutState:
    """What a checkout has checked out, where it stands against its upstream, and what's changed."""

    branch: str | None  # None on a detached HEAD
    commit: str | None  # HEAD's commit; None before the first commit
    upstream: str | None  # the branch's upstream, e.g. origin/main; None when it has none
    ahead: int | None  # commits HEAD has that the upstream lacks; None without an upstream ref
    behind: int | None  # commits the upstream has that HEAD lacks, as last fetched
    changed: list[str]  # paths staged, modified or untracked, sorted
    unfinished: str | None  # a merge, rebase, cherry-pick or revert left half done
    fetched_at: datetime | None  # when the checkout last fetched; None if it never has


def checkout_state(path: Path) -> CheckoutState:
    """The checkout's state as git reports it now. Read-only, and nothing is fetched."""
    status = ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"]
    records = iter(_run(status, cwd=path, strip=False).split("\0"))
    headers: dict[str, str] = {}
    changed: list[str] = []
    for record in records:
        kind, _, rest = record.partition(" ")
        if kind == "#":
            key, _, value = rest.partition(" ")
            headers[key] = value
        elif kind == "?":
            changed.append(rest)
        elif kind in _FIELDS_BEFORE_PATH:
            changed.append(rest.split(" ", _FIELDS_BEFORE_PATH[kind])[-1])
            if kind == "2":  # a rename or copy is followed by its original path
                next(records, None)
    branch, commit = headers.get("branch.head"), headers.get("branch.oid")
    ahead = behind = None
    if counts := headers.get("branch.ab"):  # "+<ahead> -<behind>", absent when the ref is gone
        ahead, behind = (abs(int(count)) for count in counts.split())
    return CheckoutState(
        branch=None if branch == "(detached)" else branch,
        commit=None if commit == "(initial)" else commit,
        upstream=headers.get("branch.upstream"),
        ahead=ahead,
        behind=behind,
        changed=sorted(changed),
        unfinished=unfinished_operation(path),
        fetched_at=_last_fetch(path),
    )


def _last_fetch(path: Path) -> datetime | None:
    """When the checkout last fetched: the time git last wrote its FETCH_HEAD."""
    marker = path / _run(["rev-parse", "--git-path", "FETCH_HEAD"], cwd=path)
    try:
        return datetime.fromtimestamp(marker.stat().st_mtime, UTC)
    except FileNotFoundError:
        return None


def has_changes(path: Path, file: str) -> bool:
    """True if `file` (relative to the checkout) is untracked, modified, or staged."""
    return bool(_run(["status", "--porcelain", "--untracked-files=all", "--", file], cwd=path))


def commits_since(path: Path, base: str) -> int:
    """How many commits HEAD has that `base` doesn't."""
    return int(_run(["rev-list", "--count", f"{base}..HEAD"], cwd=path))


def files_changed_since(path: Path, base: str) -> list[str]:
    """Paths whose committed content differs between `base` and HEAD, sorted."""
    listing = _run(["diff", "--name-only", "-z", base, "HEAD", "--"], cwd=path, strip=False)
    return sorted(file for file in listing.split("\0") if file)


def same_files(path: Path, ref: str, other: str, files: list[str]) -> bool:
    """True if each of `files` has the same committed content at `ref` and at `other`."""
    return not _run(["diff", "--name-only", ref, other, "--", *files], cwd=path)


def changed_files(path: Path) -> list[str]:
    """Paths with uncommitted changes (staged, modified or untracked), sorted."""
    listing = _run(["status", "--porcelain", "-z", "--untracked-files=all"], cwd=path, strip=False)
    entries = listing.split("\0")
    files: list[str] = []
    skip_next = False
    for entry in entries:
        if skip_next or not entry:
            skip_next = False
            continue
        files.append(entry[3:])
        skip_next = entry[0] in "RC"  # a rename or copy is followed by its original path
    return sorted(files)


def short_status(path: Path) -> str:
    """`git status --short --branch`: the branch line, then one line per changed file."""
    status = ["status", "--short", "--branch", "--untracked-files=all"]
    return _run(status, cwd=path, strip=False).rstrip("\n")


@dataclass(frozen=True)
class Diff:
    text: str
    clipped: bool  # something was left out: text past the limit, or new files past the count


def diff_since(path: Path, base: str, *, limit: int) -> Diff:
    """Everything the working tree changed since `base`: commits, edits and untracked files.

    At most `limit` characters, and git's output is read no further, so a huge change is never
    held in memory whole. At most MAX_NEW_FILES_IN_DIFF new files are diffed. Read-only:
    untracked files are compared with nothing instead of being added to the index. External diff
    tools are never run.
    """
    options = ["--no-color", "--no-ext-diff"]
    text, clipped = _run_capped(["diff", *options, base, "--"], cwd=path, limit=limit)
    parts = [text]
    budget = limit - len(text)
    if not clipped:
        listing = _run(["ls-files", "--others", "--exclude-standard", "-z"], cwd=path, strip=False)
        untracked = [file for file in listing.split("\0") if file]
        for file in untracked[:MAX_NEW_FILES_IN_DIFF]:
            new_file = ["diff", *options, "--no-index", "--", "/dev/null", file]
            text, clipped = _run_capped(new_file, cwd=path, limit=budget, ok_codes=(0, 1))
            parts.append(text)
            budget -= len(text)
            if clipped:
                break
        left_out = len(untracked) - MAX_NEW_FILES_IN_DIFF
        if not clipped and left_out > 0:
            clipped = True
            parts.append(f"… and {left_out} more new file{'s' if left_out > 1 else ''} not shown")
    diff = "".join(parts)
    return Diff(diff if clipped else diff.rstrip("\n"), clipped)


def resolve(path: Path, ref: str) -> str:
    """The commit `ref` (a branch, tag or hash) points to."""
    try:
        return _run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=path)
    except GitError:
        raise GitError(f"{ref} isn't a commit in {path}") from None


def read_file(path: Path, ref: str, file: str) -> bytes | None:
    """The bytes of `file` as committed at `ref`, or None if it isn't there."""
    entry = _run(["ls-tree", ref, "--", file], cwd=path)
    if not entry:
        return None
    if entry.split()[1] != "blob":
        raise GitError(f"{file} is a folder at {ref}, not a file")
    data = _run(
        ["cat-file", "blob", f"{ref}:{file}"], cwd=path, strip=False, errors="surrogateescape"
    )
    return data.encode("utf-8", "surrogateescape")


def read_files(path: Path, ref: str, files: list[str]) -> dict[str, bytes | None]:
    """The bytes of each of `files` as committed at `ref`, exactly, or None for one that isn't
    there. One git call, however many files. Refused when `ref` isn't a commit, or when one of
    `files` is a folder there.

    Only what the checkout already has is read. A partial clone that lacks one of the files
    refuses the read rather than download it, as it otherwise would.
    """
    if broken := next((file for file in files if "\n" in file), None):
        raise GitError(f"can't read {broken!r}: git reads names one per line, not a line break")
    queries = [ref, *(f"{ref}:{file}" for file in files)]
    try:
        output = _run_binary(
            ["cat-file", "--batch"], cwd=path, lines="".join(f"{q}\n" for q in queries)
        )
    except GitError as exc:
        raise GitError(f"couldn't read {ref} from what the checkout already has: {exc}") from None
    objects: list[tuple[str, bytes] | None] = []
    at = 0
    for query in queries:
        end = output.index(b"\n", at)
        line = output[at:end]
        at = end + 1
        name, _, last = line.rpartition(b" ")
        if last in (b"missing", b"ambiguous"):
            if name != query.encode():  # in the tree, but its object isn't in the checkout
                raise GitError(f"couldn't read {query} from what the checkout already has")
            objects.append(None)
            continue
        header = line.split()
        size = int(header[2])
        objects.append((header[1].decode(), output[at : at + size]))
        at += size + 1
    if objects[0] is None or objects[0][0] != "commit":
        raise GitError(f"{ref} isn't a commit in {path}")
    found: dict[str, bytes | None] = {}
    for file, obj in zip(files, objects[1:], strict=True):
        if obj is not None and obj[0] != "blob":
            raise GitError(f"{file} is a folder at {ref}, not a file")
        found[file] = obj[1] if obj is not None else None
    return found


def files_containing(path: Path, ref: str, texts: list[str]) -> list[str]:
    """Paths of the text files committed at `ref` that contain any of `texts`, sorted. One git
    call, however many files.

    Only what the checkout already has is read. A partial clone that lacks a file at `ref`
    refuses the search rather than download it, as it otherwise would.
    """
    patterns = [arg for text in texts for arg in ("-e", text)]
    search = ["grep", "--no-color", "-I", "-l", "-z", "-F", *patterns, ref, "--"]
    try:
        output = _run_binary(search, cwd=path, ok_codes=(0, 1))  # 1: no file matched
    except GitError as exc:
        raise GitError(f"couldn't search {ref} in what the checkout already has: {exc}") from None
    prefix = f"{ref}:".encode()
    return sorted(
        name.removeprefix(prefix).decode("utf-8", "replace") for name in output.split(b"\0") if name
    )


def has_commits(path: Path) -> bool:
    """Whether the checkout has any commit, on any branch."""
    return bool(_run(["rev-list", "-n", "1", "--all"], cwd=path))


def commit_files(path: Path, files: list[str], message: str) -> None:
    """Stage `files` (new or changed) and commit them alone."""
    _run(["add", "--", *files], cwd=path)
    commit_paths(path, files, message)


def commit_file(path: Path, file: str, message: str) -> None:
    """Commit `file` alone on the current branch; anything else staged stays staged, uncommitted."""
    _run(["add", "--", file], cwd=path)
    commit_paths(path, [file], message)


def commit_paths(path: Path, files: list[str], message: str) -> None:
    """Commit the staged state of `files` alone; anything else staged stays staged, uncommitted."""
    _run(["commit", "--quiet", "--message", message, "--only", "--", *files], cwd=path)


def move(path: Path, old: str, new: str) -> None:
    """Rename a tracked file (`git mv`), staging the rename."""
    _run(["mv", "--", old, new], cwd=path)


def is_tracked(path: Path, file: str) -> bool:
    try:
        _run(["ls-files", "--error-unmatch", "--", file], cwd=path)
    except GitError:
        return False
    return True


def branch_exists(path: Path, branch: str) -> bool:
    """True if the checkout's repository has a local branch named `branch`."""
    try:
        _run(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=path)
    except GitError:
        return False
    return True


def head_commit(path: Path) -> str:
    return _run(["rev-parse", "--verify", "HEAD"], cwd=path)


def add_worktree(path: Path, worktree: Path, branch: str, commit: str) -> None:
    """Create `worktree` on a new branch `branch` starting at `commit`."""
    _run(["worktree", "add", "--quiet", "-b", branch, "--", str(worktree), commit], cwd=path)


def remove_worktree(path: Path, worktree: Path) -> None:
    """Remove `worktree`. Never forced, so git refuses one with uncommitted changes."""
    _run(["worktree", "remove", "--", str(worktree)], cwd=path)


def delete_branch(path: Path, branch: str) -> None:
    """Delete the local branch `branch`, merged or not."""
    _run(["branch", "-D", "--", branch], cwd=path)


def files_at(path: Path, treeish: str, folder: str) -> list[str]:
    """Paths of the files under `folder` in `treeish` (e.g. HEAD), ignoring the working tree."""
    listing = _run(["ls-tree", "-r", "--name-only", treeish, "--", folder], cwd=path)
    return listing.splitlines()


def _run(
    args: list[str],
    *,
    cwd: Path,
    timeout: float = LOCAL_TIMEOUT_S,
    network: bool = False,
    strip: bool = True,
    ok_codes: tuple[int, ...] = (0,),
    errors: str = "replace",
) -> str:
    env = _network_env(cwd) if network else _base_env()
    with _spawn(args, cwd=cwd, env=env, stderr=subprocess.PIPE, errors=errors) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop(proc)
            raise GitError(f"git {args[0]} timed out after {timeout:g}s") from None
    if proc.returncode not in ok_codes:
        detail = stderr.strip() or f"exit code {proc.returncode}"
        raise GitError(f"git {args[0]} failed: {detail}")
    return stdout.strip() if strip else stdout


def _run_binary(
    args: list[str], *, cwd: Path, lines: str = "", ok_codes: tuple[int, ...] = (0,)
) -> bytes:
    """Run a local git command with `lines` as its input, and keep its output as the bytes git
    wrote. An exit code in `ok_codes` is success.

    It reaches no remote: a partial clone's lazy fetch of an object it lacks is refused, since
    every protocol is disallowed for it and for the fetch it would start.
    """
    with subprocess.Popen(
        ["git", "-c", "protocol.allow=never", *args],
        cwd=cwd,
        env=_base_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(lines.encode("utf-8"), timeout=LOCAL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _kill(proc)
            raise GitError(f"git {args[0]} timed out after {LOCAL_TIMEOUT_S:g}s") from None
    if proc.returncode not in ok_codes:
        detail = stderr.decode("utf-8", "replace").strip() or f"exit code {proc.returncode}"
        raise GitError(f"git {args[0]} failed: {detail}")
    return stdout


def _run_capped(
    args: list[str], *, cwd: Path, limit: int, ok_codes: tuple[int, ...] = (0,)
) -> tuple[str, bool]:
    """Run a local git command and keep at most `limit` characters of its output.

    Output is read only up to the limit; past it git is stopped, so a huge output never lands
    in memory. Returns the output and whether it was cut.
    """
    expired = threading.Event()
    with (
        tempfile.TemporaryFile() as stderr,
        _spawn(args, cwd=cwd, env=_base_env(), stderr=stderr) as proc,
    ):

        def expire() -> None:
            if proc.poll() is None:
                expired.set()
                _kill(proc)

        timer = threading.Timer(LOCAL_TIMEOUT_S, expire)
        timer.start()
        try:
            output = cast("IO[str]", proc.stdout).read(limit + 1)  # a pipe, so never None
            cut = len(output) > limit
            if cut:
                _kill(proc)
            proc.wait()
        finally:
            timer.cancel()
            timer.join()
        stderr.seek(0)
        detail = stderr.read().decode("utf-8", "replace").strip()
    if expired.is_set():
        raise GitError(f"git {args[0]} timed out after {LOCAL_TIMEOUT_S:g}s")
    if not cut and proc.returncode not in ok_codes:
        raise GitError(f"git {args[0]} failed: {detail or f'exit code {proc.returncode}'}")
    return output[:limit], cut


def _spawn(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stderr: int | IO[Any],
    errors: str = "replace",
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["git", *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        encoding="utf-8",  # not the locale's, which may be ASCII on a bare host
        errors=errors,
        start_new_session=True,  # its own process group, so a timeout can stop ssh too
    )


def _kill(proc: subprocess.Popen[Any]) -> None:
    """End git and everything it started at once, for a read-only command."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def _stop(proc: subprocess.Popen[str]) -> None:
    """End git and everything it started. SIGTERM first lets git remove a partial clone."""
    for sig, grace in ((signal.SIGTERM, TERMINATE_GRACE_S), (signal.SIGKILL, None)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, sig)
        try:
            proc.communicate(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def _base_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _network_env(cwd: Path) -> dict[str, str]:
    return {**_base_env(), "GIT_SSH_COMMAND": f"{_ssh_command(cwd)} -o BatchMode=yes"}


def _ssh_command(cwd: Path) -> str:
    """The ssh command git would use: GIT_SSH_COMMAND, core.sshCommand, GIT_SSH, or ssh."""
    if command := os.environ.get("GIT_SSH_COMMAND"):
        return command
    with contextlib.suppress(GitError):  # exits 1 when the key is unset
        if command := _run(["config", "--get", "core.sshCommand"], cwd=cwd):
            return command
    if program := os.environ.get("GIT_SSH"):
        return shlex.quote(program)
    return "ssh"
