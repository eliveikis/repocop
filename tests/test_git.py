"""Git service: remote-URL rules, clone, checkout facts, and never prompting or hanging."""

import contextlib
import os
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from repocop.services import git
from tests.conftest import push_commit, run_git

DIFF_LIMIT = 100_000


@pytest.fixture
def fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An ssh stand-in that records its arguments and environment, then fails like ssh would."""
    record = tmp_path / "ssh-record.txt"
    script = tmp_path / "fake-ssh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{record}"\n'
        f'echo "GIT_TERMINAL_PROMPT=$GIT_TERMINAL_PROMPT" >> "{record}"\n'
        'echo "Host key verification failed." >&2\n'
        "exit 255\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(script))
    return record


# ---------------------------------------------------------------- remote URLs


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo",
        "ssh://git@example.com:2222/owner/repo.git",
        "git@github.com:owner/repo.git",
        "file:///srv/git/repo.git",
    ],
)
def test_check_remote_url_accepts_supported_forms(url: str) -> None:
    assert git.check_remote_url(url) == url


def test_check_remote_url_accepts_an_existing_absolute_path(remote_repo: Path) -> None:
    assert git.check_remote_url(str(remote_repo)) == str(remote_repo)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "-oProxyCommand=touch /tmp/pwned",
        "--upload-pack=touch",
        "ext::sh -c touch% /tmp/pwned",
        "fd::17",
        "https://github.com/owner/repo .git",
        "https://github.com/owner/repo\n",
        "https://github.com/<script>",
        "http://github.com/owner/repo.git",
        "git@-oProxyCommand:owner/repo.git",
        "file://relative/repo.git",
        "relative/repo.git",
        "/no/such/local/repo.git",
    ],
)
def test_check_remote_url_rejects_unsafe_or_unsupported_forms(url: str) -> None:
    with pytest.raises(git.GitError, match="remote URL"):
        git.check_remote_url(url)


def test_remote_identity_matches_spellings_of_the_same_remote() -> None:
    spellings = [
        "https://GitHub.com/owner/repo.git",
        "https://github.com/owner/repo/",
        "git@github.com:owner/repo",
        "ssh://git@github.com:22/owner/repo.git",
    ]
    assert len({git.remote_identity(url) for url in spellings}) == 1


def test_remote_identity_matches_a_local_path_and_its_file_url(remote_repo: Path) -> None:
    assert git.remote_identity(str(remote_repo)) == git.remote_identity(f"file://{remote_repo}")


def test_remote_identity_decodes_file_urls_as_git_does(remote_repo: Path) -> None:
    encoded = f"file://{remote_repo.parent}/sam%70le.git"  # %70 is "p"
    assert git.remote_identity(encoded) == git.remote_identity(str(remote_repo))


def test_remote_identity_distinguishes_different_repos() -> None:
    assert git.remote_identity("git@github.com:owner/a.git") != git.remote_identity(
        "git@github.com:owner/b.git"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo.git",
        "https://user@github.com/owner/repo/",
        "git@github.com:owner/repo.git",
        "ssh://git@github.com:22/owner/repo.git",
    ],
)
def test_web_url_is_the_repositorys_page_on_its_host(url: str) -> None:
    assert git.web_url(url) == "https://github.com/owner/repo"


def test_web_url_keeps_the_port_of_an_https_remote() -> None:
    remote = "https://git.example.com:8443/team/repo.git"
    assert git.web_url(remote) == "https://git.example.com:8443/team/repo"


@pytest.mark.parametrize(
    "url",
    [
        "file:///srv/git/repo.git",
        "/srv/git/repo.git",
        "javascript:alert(1)",
        "https://github.com/<script>",
    ],
)
def test_web_url_is_none_unless_the_remote_is_on_a_host(url: str) -> None:
    assert git.web_url(url) is None


# ---------------------------------------------------------------- clone and checkout facts


def test_clone_creates_a_checkout_of_the_remote(remote_repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "code" / "sample"
    dest.parent.mkdir()
    git.clone(str(remote_repo), dest)
    assert git.is_checkout(dest)
    assert git.remote_url(dest) == str(remote_repo)
    assert git.default_branch(dest) == "main"


def test_clone_passes_the_url_as_one_argument_not_through_a_shell(
    remote_repo: Path, tmp_path: Path
) -> None:
    hostile = remote_repo.parent / "sample;touch${IFS}pwned.git"
    remote_repo.rename(hostile)
    dest = tmp_path / "dest"
    git.clone(str(hostile), dest)
    assert git.is_checkout(dest)
    assert not list(tmp_path.rglob("pwned"))


def test_clone_refuses_an_unsupported_url_before_running_git(tmp_path: Path) -> None:
    with pytest.raises(git.GitError, match="remote URL"):
        git.clone("ext::sh -c touch% pwned", tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_clone_failure_reports_git_error_and_leaves_nothing(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    with pytest.raises(git.GitError, match="clone failed"):
        git.clone("file:///no/such/repo.git", dest)
    assert not dest.exists()


def test_clone_over_ssh_never_prompts(fake_ssh: Path, tmp_path: Path) -> None:
    with pytest.raises(git.GitError, match="Host key verification failed"):
        git.clone("ssh://git@example.invalid/owner/repo.git", tmp_path / "dest")
    recorded = fake_ssh.read_text().splitlines()
    assert "BatchMode=yes" in recorded
    assert "GIT_TERMINAL_PROMPT=0" in recorded


def test_clone_times_out_and_stops_git_and_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hanging_ssh = tmp_path / "hanging-ssh"
    hanging_ssh.write_text("#!/bin/sh\nexec sleep 30\n")
    hanging_ssh.chmod(0o755)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(hanging_ssh))
    dest = tmp_path / "dest"
    started = time.monotonic()
    with pytest.raises(git.GitError, match="timed out"):
        git.clone("ssh://git@example.invalid/owner/repo.git", dest, timeout=0.5)
    assert time.monotonic() - started < 10
    assert not dest.exists()


def test_is_checkout_is_false_for_a_plain_directory(tmp_path: Path) -> None:
    assert not git.is_checkout(tmp_path)


def test_is_checkout_is_false_for_a_missing_path(tmp_path: Path) -> None:
    assert not git.is_checkout(tmp_path / "missing")


def test_is_checkout_is_false_for_a_subdirectory_of_a_checkout(primary_checkout: Path) -> None:
    sub = primary_checkout / "docs"
    sub.mkdir()
    assert not git.is_checkout(sub)


def test_remote_url_is_none_without_origin(tmp_path: Path) -> None:
    run_git("init", "-q", "-b", "main", cwd=tmp_path)
    assert git.remote_url(tmp_path) is None


def test_default_branch_falls_back_to_the_checked_out_branch(tmp_path: Path) -> None:
    run_git("init", "-q", "-b", "trunk", cwd=tmp_path)
    assert git.default_branch(tmp_path) == "trunk"


# ---------------------------------------------------------------- branch state and commits


def diverge(checkout: Path) -> None:
    """Give `main` and a branch `other` conflicting edits to README.md; `main` stays checked out."""
    run_git("checkout", "-q", "-b", "other", cwd=checkout)
    (checkout / "README.md").write_text("other\n")
    run_git("commit", "-qam", "other", cwd=checkout)
    run_git("checkout", "-q", "main", cwd=checkout)
    (checkout / "README.md").write_text("main\n")
    run_git("commit", "-qam", "main", cwd=checkout)


def test_current_branch_names_the_checked_out_branch(primary_checkout: Path) -> None:
    assert git.current_branch(primary_checkout) == "main"


def test_current_branch_is_none_on_a_detached_head(primary_checkout: Path) -> None:
    run_git("checkout", "-q", "--detach", cwd=primary_checkout)
    assert git.current_branch(primary_checkout) is None


def test_unfinished_operation_is_none_for_a_clean_checkout(primary_checkout: Path) -> None:
    assert git.unfinished_operation(primary_checkout) is None


def test_unfinished_operation_reports_a_merge(primary_checkout: Path) -> None:
    diverge(primary_checkout)
    with contextlib.suppress(subprocess.CalledProcessError):
        run_git("merge", "other", cwd=primary_checkout)
    assert git.unfinished_operation(primary_checkout) == "merge"


def test_unfinished_operation_reports_a_rebase(primary_checkout: Path) -> None:
    diverge(primary_checkout)
    with contextlib.suppress(subprocess.CalledProcessError):
        run_git("rebase", "other", cwd=primary_checkout)
    assert git.unfinished_operation(primary_checkout) == "rebase"


def test_has_changes_sees_untracked_and_modified_files(primary_checkout: Path) -> None:
    (primary_checkout / "new.md").write_text("new\n")
    assert git.has_changes(primary_checkout, "new.md")
    assert not git.has_changes(primary_checkout, "README.md")
    (primary_checkout / "README.md").write_text("edited\n")
    assert git.has_changes(primary_checkout, "README.md")


def test_commit_file_commits_only_that_file(primary_checkout: Path) -> None:
    (primary_checkout / "staged.txt").write_text("staged by the human\n")
    run_git("add", "staged.txt", cwd=primary_checkout)
    (primary_checkout / "README.md").write_text("modified by the human\n")
    (primary_checkout / "req.md").write_text("# Req\n")
    git.commit_file(primary_checkout, "req.md", "Add req")
    assert (
        run_git("show", "--name-only", "--format=%s", "HEAD", cwd=primary_checkout)
        == "Add req\n\nreq.md"
    )
    assert run_git("diff", "--cached", "--name-only", cwd=primary_checkout) == "staged.txt"
    assert run_git("diff", "--name-only", cwd=primary_checkout) == "README.md"


def test_branch_exists_only_for_local_branches(primary_checkout: Path) -> None:
    assert git.branch_exists(primary_checkout, "main")
    assert not git.branch_exists(primary_checkout, "feature/req-1-x")


def test_head_commit_is_the_full_hash(primary_checkout: Path) -> None:
    assert git.head_commit(primary_checkout) == run_git("rev-parse", "HEAD", cwd=primary_checkout)


def test_add_worktree_checks_out_a_new_branch_at_a_commit(
    primary_checkout: Path, tmp_path: Path
) -> None:
    base = git.head_commit(primary_checkout)
    path = tmp_path / "worktrees" / "sample" / "req-1-x"
    git.add_worktree(primary_checkout, path, "feature/req-1-x", base)
    assert git.current_branch(path) == "feature/req-1-x"
    assert git.head_commit(path) == base
    assert git.current_branch(primary_checkout) == "main"


def test_files_at_lists_committed_files_under_a_folder(primary_checkout: Path) -> None:
    skills = primary_checkout / ".claude" / "skills" / "implement"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# implement\n")
    run_git("add", ".", cwd=primary_checkout)
    run_git("commit", "-qm", "skills", cwd=primary_checkout)
    (primary_checkout / ".claude" / "skills" / "draft").mkdir()
    (primary_checkout / ".claude" / "skills" / "draft" / "SKILL.md").write_text("# draft\n")
    assert git.files_at(primary_checkout, "HEAD", ".claude/skills") == [
        ".claude/skills/implement/SKILL.md"
    ]


def test_files_at_is_empty_for_a_missing_folder(primary_checkout: Path) -> None:
    assert git.files_at(primary_checkout, "HEAD", ".claude/skills") == []


def test_is_tracked_distinguishes_committed_and_new_files(primary_checkout: Path) -> None:
    (primary_checkout / "new.md").write_text("new\n")
    assert git.is_tracked(primary_checkout, "README.md")
    assert not git.is_tracked(primary_checkout, "new.md")


def test_move_and_commit_paths_commit_only_the_rename(primary_checkout: Path) -> None:
    (primary_checkout / "staged.txt").write_text("the human's\n")
    run_git("add", "staged.txt", cwd=primary_checkout)
    git.move(primary_checkout, "README.md", "INTRO.md")
    git.commit_paths(primary_checkout, ["README.md", "INTRO.md"], "Rename")
    changed = run_git("show", "--name-status", "--format=", "-M", "HEAD", cwd=primary_checkout)
    assert changed.split() == ["R100", "README.md", "INTRO.md"]
    assert run_git("diff", "--cached", "--name-only", cwd=primary_checkout) == "staged.txt"


def test_common_dir_is_shared_by_a_checkout_and_its_worktrees(
    primary_checkout: Path, tmp_path: Path
) -> None:
    worktree = tmp_path / "wt"
    git.add_worktree(primary_checkout, worktree, "feature/x", git.head_commit(primary_checkout))
    assert git.common_dir(worktree) == git.common_dir(primary_checkout)
    assert git.common_dir(primary_checkout) == (primary_checkout / ".git").resolve()


def test_commits_since_counts_commits_after_a_base(primary_checkout: Path) -> None:
    base = git.head_commit(primary_checkout)
    for name in ("a.txt", "b.txt"):
        (primary_checkout / name).write_text(f"{name}\n")
        run_git("add", name, cwd=primary_checkout)
        run_git("commit", "-qm", name, cwd=primary_checkout)
    assert git.commits_since(primary_checkout, base) == 2
    assert git.commits_since(primary_checkout, git.head_commit(primary_checkout)) == 0


def test_changed_files_lists_uncommitted_and_untracked_paths(primary_checkout: Path) -> None:
    assert git.changed_files(primary_checkout) == []
    (primary_checkout / "README.md").write_text("edited\n")
    (primary_checkout / "docs").mkdir()
    (primary_checkout / "docs" / "new file.md").write_text("new\n")
    assert git.changed_files(primary_checkout) == ["README.md", "docs/new file.md"]


def test_short_status_shows_the_branch_and_changed_files(primary_checkout: Path) -> None:
    (primary_checkout / "README.md").write_text("edited\n")
    (primary_checkout / "new.txt").write_text("new\n")
    status = git.short_status(primary_checkout)
    assert status.splitlines()[0].startswith("## main")
    assert " M README.md" in status.splitlines()
    assert "?? new.txt" in status.splitlines()


def test_diff_since_covers_commits_edits_and_new_files(primary_checkout: Path) -> None:
    base = git.head_commit(primary_checkout)
    (primary_checkout / "committed.txt").write_text("committed line\n")
    run_git("add", "committed.txt", cwd=primary_checkout)
    run_git("commit", "-qm", "Add committed.txt", cwd=primary_checkout)
    (primary_checkout / "README.md").write_text("# sample\nedited line\n")
    (primary_checkout / "untracked.txt").write_text("untracked line\n")
    diff = git.diff_since(primary_checkout, base, limit=DIFF_LIMIT)
    assert "+committed line" in diff.text
    assert "+edited line" in diff.text
    assert "+untracked line" in diff.text
    assert "b/untracked.txt" in diff.text
    assert not diff.clipped


def test_diff_since_is_empty_without_changes(primary_checkout: Path) -> None:
    head = git.head_commit(primary_checkout)
    assert git.diff_since(primary_checkout, head, limit=DIFF_LIMIT) == git.Diff("", clipped=False)


def test_diff_since_leaves_the_index_alone(primary_checkout: Path) -> None:
    (primary_checkout / "untracked.txt").write_text("untracked line\n")
    git.diff_since(primary_checkout, git.head_commit(primary_checkout), limit=DIFF_LIMIT)
    assert "?? untracked.txt" in git.short_status(primary_checkout).splitlines()


@pytest.mark.parametrize("name", ["README.md", "new.txt"])
def test_diff_since_stops_reading_at_the_limit(primary_checkout: Path, name: str) -> None:
    (primary_checkout / name).write_text("a long line of text\n" * 100_000)
    diff = git.diff_since(primary_checkout, git.head_commit(primary_checkout), limit=1000)
    assert diff.clipped
    assert len(diff.text) == 1000
    assert f"b/{name}" in diff.text


def test_diff_since_counts_new_files_it_leaves_out_as_clipped(
    primary_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git, "MAX_NEW_FILES_IN_DIFF", 2)
    for name in ("a.txt", "b.txt", "c.txt"):
        (primary_checkout / name).write_text(f"{name}\n")
    diff = git.diff_since(primary_checkout, git.head_commit(primary_checkout), limit=DIFF_LIMIT)
    assert diff.clipped
    assert "b/b.txt" in diff.text and "b/c.txt" not in diff.text
    assert diff.text.endswith("… and 1 more new file not shown")


def test_read_file_returns_a_files_bytes_at_a_ref(primary_checkout: Path) -> None:
    (primary_checkout / "data.bin").write_bytes(b"\x89\xff\x00caf\xc3\xa9")
    run_git("add", "data.bin", cwd=primary_checkout)
    run_git("commit", "-qm", "data", cwd=primary_checkout)
    (primary_checkout / "data.bin").write_bytes(b"changed in the working tree")
    assert git.read_file(primary_checkout, "main", "data.bin") == b"\x89\xff\x00caf\xc3\xa9"


def test_read_file_is_none_for_a_path_missing_at_the_ref(primary_checkout: Path) -> None:
    assert git.read_file(primary_checkout, "main", "nope/missing.md") is None


def test_read_file_refuses_a_folder(primary_checkout: Path) -> None:
    (primary_checkout / "docs").mkdir()
    (primary_checkout / "docs" / "a.md").write_text("a\n")
    run_git("add", "docs", cwd=primary_checkout)
    run_git("commit", "-qm", "docs", cwd=primary_checkout)
    with pytest.raises(git.GitError, match="folder"):
        git.read_file(primary_checkout, "main", "docs")


def test_read_files_returns_each_files_bytes_at_a_ref_exactly(primary_checkout: Path) -> None:
    (primary_checkout / "docs").mkdir()
    (primary_checkout / "docs" / "a.md").write_bytes(b"line\r\nnext\n")
    (primary_checkout / "data.bin").write_bytes(b"\x89\xff\x00caf\xc3\xa9\n")
    run_git("add", "docs", "data.bin", cwd=primary_checkout)
    run_git("commit", "-qm", "files", cwd=primary_checkout)
    (primary_checkout / "data.bin").write_bytes(b"changed in the working tree")
    files = git.read_files(primary_checkout, "main", ["docs/a.md", "data.bin", "nope/missing.md"])
    assert files == {
        "docs/a.md": b"line\r\nnext\n",
        "data.bin": b"\x89\xff\x00caf\xc3\xa9\n",
        "nope/missing.md": None,
    }


def test_read_files_runs_git_once_however_many_files(
    primary_checkout: Path, git_calls: Callable[[], list[list[str]]]
) -> None:
    git.read_files(primary_checkout, "main", [f"file-{n}.md" for n in range(20)])
    assert len(git_calls()) == 1


def test_read_files_refuses_a_folder(primary_checkout: Path) -> None:
    (primary_checkout / "docs").mkdir()
    (primary_checkout / "docs" / "a.md").write_text("a\n")
    run_git("add", "docs", cwd=primary_checkout)
    run_git("commit", "-qm", "docs", cwd=primary_checkout)
    with pytest.raises(git.GitError, match="docs is a folder at main"):
        git.read_files(primary_checkout, "main", ["docs"])


def test_read_files_refuses_a_ref_that_is_not_a_commit(primary_checkout: Path) -> None:
    with pytest.raises(git.GitError, match="no-such-branch isn't a commit"):
        git.read_files(primary_checkout, "no-such-branch", ["README.md"])


def test_read_files_downloads_nothing_a_partial_clone_lacks(
    remote_repo: Path, tmp_path: Path
) -> None:
    run_git("config", "uploadpack.allowFilter", "true", cwd=remote_repo)
    partial = tmp_path / "partial"
    run_git("clone", "-q", "--filter=blob:none", remote_repo.as_uri(), str(partial), cwd=tmp_path)
    push_commit(remote_repo, tmp_path, name="new.md")
    run_git("fetch", "-q", "origin", cwd=partial)
    blob = run_git("rev-parse", "origin/main:new.md", cwd=partial)
    with pytest.raises(git.GitError, match="from what the checkout already has"):
        git.read_files(partial, "origin/main", ["new.md"])
    lacking = run_git("rev-list", "--objects", "--missing=print", "origin/main", cwd=partial)
    assert f"?{blob}" in lacking.split()


def test_read_files_refuses_a_name_with_a_line_break(primary_checkout: Path) -> None:
    with pytest.raises(git.GitError, match="line break"):
        git.read_files(primary_checkout, "main", ["README.md", "two\nlines.md"])


def test_files_containing_lists_the_files_at_a_ref_with_any_of_the_texts(
    primary_checkout: Path,
) -> None:
    (primary_checkout / "a dir").mkdir()
    (primary_checkout / "a dir" / "one.md").write_text("intro\n<!-- marked -->\n")
    (primary_checkout / "two.sh").write_text("#!/bin/sh\n# marked too\n")
    (primary_checkout / "data.bin").write_bytes(b"\x00<!-- marked -->\n")
    run_git("add", "-A", cwd=primary_checkout)
    run_git("commit", "-qm", "files", cwd=primary_checkout)
    (primary_checkout / "README.md").write_text("<!-- marked -->\n")  # not committed
    found = git.files_containing(primary_checkout, "main", ["<!-- marked -->", "# marked too"])
    assert found == ["a dir/one.md", "two.sh"]
    assert git.files_containing(primary_checkout, "main", ["nowhere"]) == []


def test_files_containing_downloads_nothing_a_partial_clone_lacks(
    remote_repo: Path, tmp_path: Path
) -> None:
    run_git("config", "uploadpack.allowFilter", "true", cwd=remote_repo)
    partial = tmp_path / "partial"
    run_git("clone", "-q", "--filter=blob:none", remote_repo.as_uri(), str(partial), cwd=tmp_path)
    push_commit(remote_repo, tmp_path, name="new.md")
    run_git("fetch", "-q", "origin", cwd=partial)
    blob = run_git("rev-parse", "origin/main:new.md", cwd=partial)
    with pytest.raises(git.GitError, match="in what the checkout already has"):
        git.files_containing(partial, "origin/main", ["upstream"])
    lacking = run_git("rev-list", "--objects", "--missing=print", "origin/main", cwd=partial)
    assert f"?{blob}" in lacking.split()


def test_has_commits_is_false_only_before_the_first_commit(
    primary_checkout: Path, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    run_git("init", "-q", str(empty), cwd=tmp_path)
    assert not git.has_commits(empty)
    assert git.has_commits(primary_checkout)


def test_resolve_gives_a_refs_commit(primary_checkout: Path) -> None:
    assert git.resolve(primary_checkout, "main") == git.head_commit(primary_checkout)
    with pytest.raises(git.GitError):
        git.resolve(primary_checkout, "no-such-branch")


def test_commit_files_commits_exactly_the_given_files(primary_checkout: Path) -> None:
    (primary_checkout / "a.txt").write_text("a\n")
    (primary_checkout / "b.txt").write_text("b\n")
    (primary_checkout / "c.txt").write_text("c\n")
    git.commit_files(primary_checkout, ["a.txt", "b.txt"], "Add a and b")
    assert sorted(
        run_git("show", "--name-only", "--format=", "HEAD", cwd=primary_checkout).split()
    ) == ["a.txt", "b.txt"]
    assert "?? c.txt" in git.short_status(primary_checkout).splitlines()


# ---------------------------------------------------------------- checkout state and fetch


def test_checkout_state_names_the_branch_and_its_upstream(primary_checkout: Path) -> None:
    state = git.checkout_state(primary_checkout)
    assert (state.branch, state.upstream) == ("main", "origin/main")
    assert (state.ahead, state.behind) == (0, 0)
    assert state.commit == run_git("rev-parse", "HEAD", cwd=primary_checkout)
    assert state.changed == []
    assert state.unfinished is None


def test_checkout_state_gives_the_commit_of_a_detached_head(primary_checkout: Path) -> None:
    run_git("checkout", "-q", "--detach", cwd=primary_checkout)
    state = git.checkout_state(primary_checkout)
    assert state.branch is None
    assert state.commit == run_git("rev-parse", "HEAD", cwd=primary_checkout)
    assert (state.upstream, state.ahead, state.behind) == (None, None, None)


def test_checkout_state_lists_staged_modified_untracked_and_renamed_files(
    primary_checkout: Path,
) -> None:
    (primary_checkout / "old.md").write_text("old\n")
    run_git("add", "old.md", cwd=primary_checkout)
    run_git("commit", "-qm", "Add old.md", cwd=primary_checkout)
    (primary_checkout / "README.md").write_text("edited\n")
    (primary_checkout / "with space.md").write_text("new\n")
    (primary_checkout / "staged.txt").write_text("staged\n")
    run_git("add", "staged.txt", cwd=primary_checkout)
    run_git("mv", "old.md", "renamed.md", cwd=primary_checkout)
    state = git.checkout_state(primary_checkout)
    assert state.changed == ["README.md", "renamed.md", "staged.txt", "with space.md"]


def test_checkout_state_counts_commits_ahead_of_and_behind_the_upstream_as_last_fetched(
    primary_checkout: Path, remote_repo: Path, tmp_path: Path
) -> None:
    (primary_checkout / "local.txt").write_text("local\n")
    git.commit_files(primary_checkout, ["local.txt"], "Local work")
    push_commit(remote_repo, tmp_path)
    state = git.checkout_state(primary_checkout)
    assert (state.ahead, state.behind) == (1, 0)
    git.fetch(primary_checkout)
    state = git.checkout_state(primary_checkout)
    assert (state.ahead, state.behind) == (1, 1)


def test_checkout_state_has_no_upstream_on_a_new_local_branch(primary_checkout: Path) -> None:
    run_git("checkout", "-q", "-b", "topic", cwd=primary_checkout)
    state = git.checkout_state(primary_checkout)
    assert (state.branch, state.upstream, state.ahead, state.behind) == ("topic", None, None, None)


def test_checkout_state_names_an_upstream_that_is_gone(primary_checkout: Path) -> None:
    run_git("checkout", "-q", "-b", "topic", cwd=primary_checkout)
    run_git("push", "-q", "-u", "origin", "topic", cwd=primary_checkout)
    run_git("update-ref", "-d", "refs/remotes/origin/topic", cwd=primary_checkout)
    state = git.checkout_state(primary_checkout)
    assert (state.upstream, state.ahead, state.behind) == ("origin/topic", None, None)


def test_checkout_state_reports_an_unfinished_merge(primary_checkout: Path) -> None:
    diverge(primary_checkout)
    with contextlib.suppress(subprocess.CalledProcessError):
        run_git("merge", "other", cwd=primary_checkout)
    assert git.checkout_state(primary_checkout).unfinished == "merge"


def test_checkout_state_of_a_branch_without_commits(tmp_path: Path) -> None:
    run_git("init", "-q", "-b", "main", cwd=tmp_path)
    state = git.checkout_state(tmp_path)
    assert (state.branch, state.commit) == ("main", None)


def test_checkout_state_tells_when_the_checkout_last_fetched(primary_checkout: Path) -> None:
    assert git.checkout_state(primary_checkout).fetched_at is None
    git.fetch(primary_checkout)
    fetched_at = git.checkout_state(primary_checkout).fetched_at
    assert fetched_at is not None
    assert abs((datetime.now(UTC) - fetched_at).total_seconds()) < 60


def test_checkout_state_leaves_the_index_untouched(primary_checkout: Path) -> None:
    later = time.time() + 60
    os.utime(primary_checkout / "README.md", (later, later))  # git status would refresh the index
    index = primary_checkout / ".git" / "index"
    before = index.read_bytes()
    assert git.checkout_state(primary_checkout).changed == []
    assert index.read_bytes() == before


def test_fetch_updates_the_remote_tracking_branch(
    primary_checkout: Path, remote_repo: Path, tmp_path: Path
) -> None:
    pushed = push_commit(remote_repo, tmp_path)
    assert run_git("rev-parse", "origin/main", cwd=primary_checkout) != pushed
    git.fetch(primary_checkout)
    assert run_git("rev-parse", "origin/main", cwd=primary_checkout) == pushed


def test_fetch_leaves_the_working_tree_index_head_and_local_refs_alone(
    primary_checkout: Path, remote_repo: Path, tmp_path: Path
) -> None:
    run_git("branch", "other", cwd=primary_checkout)
    (primary_checkout / "README.md").write_text("edited by the human\n")
    (primary_checkout / "staged.txt").write_text("staged by the human\n")
    run_git("add", "staged.txt", cwd=primary_checkout)
    (primary_checkout / "untracked.txt").write_text("untracked\n")
    push_commit(remote_repo, tmp_path)
    run_git("tag", "v1", cwd=tmp_path / "pusher")
    run_git("push", "-q", "origin", "v1", cwd=tmp_path / "pusher")

    def local_state() -> list[str]:
        return [
            run_git("status", "--porcelain", cwd=primary_checkout),
            run_git("symbolic-ref", "HEAD", cwd=primary_checkout),
            run_git("for-each-ref", "refs/heads", "refs/tags", cwd=primary_checkout),
            run_git("diff", "--cached", cwd=primary_checkout),
            (primary_checkout / "README.md").read_text(),
        ]

    before = local_state()
    git.fetch(primary_checkout)
    assert local_state() == before


def test_fetch_ignores_the_refspecs_the_checkout_configures(
    primary_checkout: Path, remote_repo: Path, tmp_path: Path
) -> None:
    to_local_branches = "+refs/heads/*:refs/heads/mirrored/*"
    run_git("config", "remote.origin.fetch", to_local_branches, cwd=primary_checkout)
    run_git(
        "config", "--add", "remote.origin.fetch", "+refs/tags/*:refs/tags/*", cwd=primary_checkout
    )
    pushed = push_commit(remote_repo, tmp_path)
    run_git("tag", "v1", cwd=tmp_path / "pusher")
    run_git("push", "-q", "origin", "v1", cwd=tmp_path / "pusher")
    before = run_git("for-each-ref", "refs/heads", "refs/tags", cwd=primary_checkout)
    git.fetch(primary_checkout)
    assert run_git("for-each-ref", "refs/heads", "refs/tags", cwd=primary_checkout) == before
    assert run_git("rev-parse", "origin/main", cwd=primary_checkout) == pushed


def test_fetch_never_prunes(primary_checkout: Path, remote_repo: Path) -> None:
    run_git("push", "-q", "origin", "main:short-lived", cwd=primary_checkout)
    run_git("branch", "-D", "short-lived", cwd=remote_repo)
    run_git("config", "fetch.prune", "true", cwd=primary_checkout)
    git.fetch(primary_checkout)
    assert run_git("rev-parse", "--verify", "origin/short-lived", cwd=primary_checkout)


def test_fetch_failure_reports_git_error(primary_checkout: Path) -> None:
    run_git("remote", "set-url", "origin", "file:///no/such/repo.git", cwd=primary_checkout)
    with pytest.raises(git.GitError, match="fetch failed"):
        git.fetch(primary_checkout)


def test_fetch_refuses_an_unsupported_origin_before_running_git(primary_checkout: Path) -> None:
    run_git("remote", "set-url", "origin", "ext::sh -c touch% pwned", cwd=primary_checkout)
    with pytest.raises(git.GitError, match="remote URL"):
        git.fetch(primary_checkout)
    assert not (primary_checkout / "pwned").exists()
    assert not (primary_checkout / ".git" / "FETCH_HEAD").exists()


def test_fetch_over_ssh_never_prompts(fake_ssh: Path, primary_checkout: Path) -> None:
    remote = "ssh://git@example.invalid/owner/repo.git"
    run_git("remote", "set-url", "origin", remote, cwd=primary_checkout)
    with pytest.raises(git.GitError, match="Host key verification failed"):
        git.fetch(primary_checkout)
    recorded = fake_ssh.read_text().splitlines()
    assert "BatchMode=yes" in recorded
    assert "GIT_TERMINAL_PROMPT=0" in recorded


def test_fetch_times_out_and_stops_git_and_ssh(
    primary_checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hanging_ssh = tmp_path / "hanging-ssh"
    hanging_ssh.write_text("#!/bin/sh\nexec sleep 30\n")
    hanging_ssh.chmod(0o755)
    monkeypatch.setenv("GIT_SSH_COMMAND", str(hanging_ssh))
    remote = "ssh://git@example.invalid/owner/repo.git"
    run_git("remote", "set-url", "origin", remote, cwd=primary_checkout)
    started = time.monotonic()
    with pytest.raises(git.GitError, match="timed out"):
        git.fetch(primary_checkout, timeout=0.5)
    assert time.monotonic() - started < 10


# ---------------------------------------------------------------- push


def branch_with_a_commit(checkout: Path, branch: str = "feature/req-1-x") -> str:
    """Check out a new `branch` with one commit on it, and return that commit."""
    run_git("checkout", "-q", "-b", branch, cwd=checkout)
    (checkout / "work.txt").write_text("work\n")
    git.commit_files(checkout, ["work.txt"], "Work")
    return run_git("rev-parse", "HEAD", cwd=checkout)


def test_push_sends_the_branch_and_makes_it_the_upstream(
    primary_checkout: Path, remote_repo: Path
) -> None:
    commit = branch_with_a_commit(primary_checkout)
    git.push(primary_checkout, "feature/req-1-x")
    assert run_git("rev-parse", "feature/req-1-x", cwd=remote_repo) == commit
    assert git.checkout_state(primary_checkout).upstream == "origin/feature/req-1-x"


def test_push_sends_no_other_branch_and_no_tags(primary_checkout: Path, remote_repo: Path) -> None:
    run_git("branch", "private", cwd=primary_checkout)
    branch_with_a_commit(primary_checkout)
    run_git("tag", "-a", "v1", "-m", "v1", cwd=primary_checkout)
    run_git("config", "push.followTags", "true", cwd=primary_checkout)
    run_git("config", "remote.origin.push", "+refs/heads/*:refs/heads/*", cwd=primary_checkout)
    git.push(primary_checkout, "feature/req-1-x")
    refs = run_git("for-each-ref", "--format=%(refname)", cwd=remote_repo).splitlines()
    assert refs == ["refs/heads/feature/req-1-x", "refs/heads/main"]


def test_push_refuses_when_the_remote_branch_has_other_commits(
    primary_checkout: Path, remote_repo: Path, tmp_path: Path
) -> None:
    branch_with_a_commit(primary_checkout)
    git.push(primary_checkout, "feature/req-1-x")
    run_git("clone", "-q", "-b", "feature/req-1-x", str(remote_repo), "other", cwd=tmp_path)
    (tmp_path / "other" / "theirs.txt").write_text("theirs\n")
    run_git("add", "theirs.txt", cwd=tmp_path / "other")
    run_git("commit", "-qm", "Theirs", cwd=tmp_path / "other")
    run_git("push", "-q", "origin", "feature/req-1-x", cwd=tmp_path / "other")
    theirs = run_git("rev-parse", "feature/req-1-x", cwd=remote_repo)
    (primary_checkout / "more.txt").write_text("more\n")
    git.commit_files(primary_checkout, ["more.txt"], "More")
    with pytest.raises(git.GitError, match="has commits this branch doesn't"):
        git.push(primary_checkout, "feature/req-1-x")
    assert run_git("rev-parse", "feature/req-1-x", cwd=remote_repo) == theirs


def test_push_never_passes_a_force_flag(
    primary_checkout: Path, git_calls: Callable[[], list[list[str]]]
) -> None:
    branch_with_a_commit(primary_checkout)
    git.push(primary_checkout, "feature/req-1-x")
    pushes = [call for call in git_calls() if call[0] == "push"]
    assert len(pushes) == 1
    assert not [arg for arg in pushes[0] if arg == "-f" or arg.startswith(("--force", "+"))]


def test_push_urls_are_origins_url_unless_it_pushes_elsewhere(
    primary_checkout: Path, remote_repo: Path
) -> None:
    assert git.push_urls(primary_checkout) == [str(remote_repo)]
    elsewhere = ["https://example.com/owner/fork.git", "git@example.com:owner/mirror.git"]
    run_git("remote", "set-url", "--push", "origin", elsewhere[0], cwd=primary_checkout)
    run_git("remote", "set-url", "--push", "--add", "origin", elsewhere[1], cwd=primary_checkout)
    assert git.push_urls(primary_checkout) == elsewhere


def test_push_urls_are_as_git_rewrites_them(primary_checkout: Path, remote_repo: Path) -> None:
    rewritten = "https://example.com/owner/fork.git"
    run_git("config", f"url.{rewritten}.pushInsteadOf", str(remote_repo), cwd=primary_checkout)
    assert git.push_urls(primary_checkout) == [rewritten]


def test_push_urls_refuses_an_unsupported_url(primary_checkout: Path) -> None:
    run_git("remote", "set-url", "--push", "origin", "ext::sh -c true", cwd=primary_checkout)
    with pytest.raises(git.GitError, match="remote URL"):
        git.push_urls(primary_checkout)


def test_push_refuses_an_unsupported_push_url_before_running_git(primary_checkout: Path) -> None:
    branch_with_a_commit(primary_checkout)
    hostile = "ext::sh -c touch% pwned"
    run_git("remote", "set-url", "--push", "origin", hostile, cwd=primary_checkout)
    with pytest.raises(git.GitError, match="remote URL"):
        git.push(primary_checkout, "feature/req-1-x")
    assert not (primary_checkout / "pwned").exists()


def test_push_failure_reports_git_error(primary_checkout: Path) -> None:
    branch_with_a_commit(primary_checkout)
    gone = "file:///no/such/repo.git"
    run_git("remote", "set-url", "--push", "origin", gone, cwd=primary_checkout)
    with pytest.raises(git.GitError, match="push failed"):
        git.push(primary_checkout, "feature/req-1-x")


def test_files_changed_since_lists_what_commits_changed(primary_checkout: Path) -> None:
    base = run_git("rev-parse", "HEAD", cwd=primary_checkout)
    (primary_checkout / "b.txt").write_text("b\n")
    (primary_checkout / "README.md").write_text("edited\n")
    git.commit_files(primary_checkout, ["b.txt", "README.md"], "Change two files")
    (primary_checkout / "uncommitted.txt").write_text("not yet\n")
    assert git.files_changed_since(primary_checkout, base) == ["README.md", "b.txt"]
