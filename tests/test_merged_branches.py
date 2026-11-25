"""Merged branches on a repository's page: the local branches whose pull request GitHub merged,
with their worktrees, read after the page renders, and removed only on the developer's
confirmation, each refused where work would be lost, with nothing else touched."""

import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import add_requirement, record_session, run_git
from tests.fakes.fake_gh import FakeGh
from tests.test_board import card, stamp

PAGE = "/repositories/1"
READ = f"{PAGE}?pull_requests=true"
PREVIEW = f"{PAGE}/merged-branches/preview"
REMOVE = f"{PAGE}/merged-branches/remove"


def pull(number: int) -> str:
    return f"https://github.com/owner/sample/pull/{number}"


@pytest.fixture
def registered(client: TestClient, github_checkout: Path, fake_gh: FakeGh) -> Path:
    """Repository `sample` on github.com, registered from its checkout."""
    client.post("/repositories", data={"name": "sample", "default_branch": "main"})
    return github_checkout


def merged(
    repo: Path,
    fake_gh: FakeGh,
    branch: str,
    number: int,
    *,
    worktree: Path | None = None,
    fork: bool = False,
    reported: str = "merged",
) -> str:
    """A branch with one commit, pushed to `origin`, checked out in `worktree` if given, whose
    pull request GitHub reports as `reported`: merged at its tip, `open`, or `none` when it has
    none. Returns its tip."""
    file = f"{branch.replace('/', '-')}.txt"
    run_git("switch", "-q", "-c", branch, "main", cwd=repo)
    (repo / file).write_text(f"{branch}\n")
    run_git("add", file, cwd=repo)
    run_git("commit", "-qm", f"Work on {branch}", cwd=repo)
    run_git("switch", "-q", "main", cwd=repo)
    run_git("push", "-q", "origin", branch, cwd=repo)
    tip = run_git("rev-parse", branch, cwd=repo)
    if worktree is not None:
        run_git("worktree", "add", "-q", "--", str(worktree), branch, cwd=repo)
    if reported == "open":
        fake_gh.add_pull_request(branch, pull(number), fork=fork)
    elif reported == "merged":
        fake_gh.add_merged_pull_request(branch, pull(number), tip, fork=fork)
    return tip


def squash_merge(repo: Path, remote: Path, branch: str, tmp_path: Path) -> None:
    """Squash-merge `branch` into `main` on the remote, as GitHub does, and fetch it."""
    clone = tmp_path / "merger"
    if not clone.exists():
        run_git("clone", "-q", str(remote), str(clone), cwd=tmp_path)
    run_git("fetch", "-q", "origin", cwd=clone)
    run_git("merge", "--squash", f"origin/{branch}", cwd=clone)
    run_git("commit", "-qm", f"Merge {branch}", cwd=clone)
    run_git("push", "-q", "origin", "main", cwd=clone)
    run_git("fetch", "-q", "origin", cwd=repo)


def commit_on(worktree: Path, file: str) -> None:
    (worktree / file).write_text("more\n")
    run_git("add", file, cwd=worktree)
    run_git("commit", "-qm", f"Add {file}", cwd=worktree)


def listing(html: str) -> str:
    """The merged branches a page lists, or says it can't."""
    found = re.search(r'<div id="merged-branches-list"[^>]*>(.*?)</div>', html, re.DOTALL)
    assert found, "no merged branches section"
    return found[1]


def picked(section: str) -> list[str]:
    return re.findall(r'name="branch" value="([^"]+)" checked', section)


def row(section: str, branch: str) -> str:
    rows: list[str] = re.findall(r'<tr class="merged-branch">(.*?)</tr>', section, re.DOTALL)
    found = [r for r in rows if f"<code>{branch}</code>" in r]
    assert len(found) == 1, f"{branch}: {len(found)} rows"
    return found[0]


def outcomes(html: str) -> dict[str, str]:
    """What the page says of each branch after removing: removed or refused, with why."""
    return {
        branch: f"{kind}: {text}"
        for kind, branch, text in re.findall(
            r'<li class="outcome (removed|refused)"><code>([^<]+)</code>(.*?)</li>',
            html,
            re.DOTALL,
        )
    }


def branches(repo: Path) -> set[str]:
    listed = run_git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=repo)
    return set(listed.split())


def worktree_paths(repo: Path) -> set[str]:
    listed = run_git("worktree", "list", "--porcelain", cwd=repo)
    return set(re.findall(r"^worktree (.*)$", listed, re.MULTILINE))


def test_repository_page_lists_merged_branches_with_their_pull_request_and_worktree(
    registered: Path, client: TestClient, fake_gh: FakeGh, remote_repo: Path, tmp_path: Path
) -> None:
    repo, wt = registered, tmp_path / "wt"
    inside = repo / ".wt" / "inside"  # some agent tools keep worktrees in the checkout's folder
    merged(repo, fake_gh, "feature", 1, worktree=wt / "feature")
    squash_merge(repo, remote_repo, "feature", tmp_path)  # so main doesn't contain its commit
    merged(repo, fake_gh, "agent/inside", 2, worktree=inside)
    merged(repo, fake_gh, "gone", 3, worktree=wt / "gone")
    shutil.rmtree(wt / "gone")
    merged(repo, fake_gh, "plain", 4)
    merged(repo, fake_gh, "moved", 5, worktree=wt / "moved")
    commit_on(wt / "moved", "late.txt")  # committed to since its merge
    merged(repo, fake_gh, "open-work", 6, reported="open")
    merged(repo, fake_gh, "forked", 7, fork=True)
    merged(repo, fake_gh, "contained", 8, reported="none")
    squash_merge(repo, remote_repo, "contained", tmp_path)  # on main, but through no pull request
    client.post("/repositories/1/sync", data={"create": ["CLAUDE.md"]})
    sync_tip = run_git("rev-parse", "agent/template-sync-1", cwd=repo)
    fake_gh.add_merged_pull_request("agent/template-sync-1", pull(9), sync_tip)
    add_requirement(repo, f"{stamp(1)}feature.md", folder="specs/changes/archive")

    calls = len(fake_gh.calls)
    before = client.get(PAGE).text
    assert len(fake_gh.calls) == calls  # the page shows before GitHub answers
    assert "not read yet" in listing(before)
    assert f'href="http://testserver{READ}#merged-branches"' in listing(before)
    assert "still here" not in card(before, "feature")

    html = client.get(READ).text
    section = listing(html)
    assert picked(section) == ["agent/inside", "feature", "gone", "plain"]
    assert f'<a href="{pull(1)}"' in row(section, "feature")
    assert f"<code>{wt / 'feature'}</code>" in row(section, "feature")
    assert f"<code>{inside}</code>" in row(section, "agent/inside")
    assert "folder gone" in row(section, "gone") and "folder gone" not in row(section, "feature")
    assert "no worktree" in row(section, "plain")
    assert f'action="http://testserver{PREVIEW}"' in section
    assert "newest" not in section  # far from the limit
    still = card(html, "feature")
    assert "<code>feature</code> is still here" in still and 'href="#merged-branches"' in still
    fragment = client.get("/board?repository=1").text
    assert '<div id="merged-branches-list" hx-swap-oob="true">' in fragment
    assert picked(listing(fragment)) == picked(section)
    asked = {tuple(call[:2]) for call in fake_gh.calls}
    assert asked <= {("auth", "status"), ("pr", "list")}  # reading changes nothing on GitHub
    assert branches(repo) >= {"feature", "agent/inside", "gone", "plain", "moved"}


def test_removing_merged_branches_shows_what_goes_and_removes_only_what_is_confirmed(
    registered: Path, client: TestClient, fake_gh: FakeGh, tmp_path: Path
) -> None:
    repo, wt = registered, tmp_path / "wt"
    merged(repo, fake_gh, "feature", 1, worktree=wt / "feature")
    (wt / "feature" / ".gitignore").write_text(".env\n.venv/\n")
    run_git("add", ".gitignore", cwd=wt / "feature")
    run_git("commit", "-qm", "Ignore local files", cwd=wt / "feature")
    fake_gh.add_merged_pull_request("feature", pull(1), run_git("rev-parse", "feature", cwd=repo))
    (wt / "feature" / ".env").write_text("SECRET=1\n")
    (wt / "feature" / ".venv" / "lib").mkdir(parents=True)
    (wt / "feature" / ".venv" / "lib" / "x.py").write_text("")
    merged(repo, fake_gh, "gone", 2, worktree=wt / "gone")
    shutil.rmtree(wt / "gone")
    merged(repo, fake_gh, "plain", 3)
    merged(repo, fake_gh, "kept", 4, worktree=wt / "kept")
    closed = {"event": "closed", "reason": "exit", "cwd": str(wt / "feature")}
    record_session(repo, {"event": "working", "ago": 5, "cwd": closed["cwd"]}, closed, session="s1")
    head = run_git("rev-parse", "HEAD", cwd=repo), run_git("status", "--porcelain", cwd=repo)
    picks = {"branch": ["feature", "gone", "plain"]}

    preview = client.post(PREVIEW, data=picks)
    assert preview.status_code == 200, preview.text
    shown = preview.text
    assert f"<code>{wt / 'feature'}</code>" in shown
    assert "<code>.env</code>" in shown and "<code>.venv/</code>" in shown
    assert "folder is gone" in shown and "no worktree" in shown
    assert "<code>kept</code>" not in shown
    assert f'action="http://testserver{REMOVE}"' in shown
    hidden = re.findall(r'<input type="hidden" name="branch" value="([^"]+)"', shown)
    assert hidden == ["feature", "gone", "plain"]
    assert branches(repo) >= {"feature", "gone", "plain", "kept"}  # nothing went yet
    assert (wt / "feature" / ".env").exists()

    result = client.post(REMOVE, data=picks)
    assert result.status_code == 200, result.text
    said = outcomes(result.text)
    assert set(said) == {"feature", "gone", "plain"}
    assert said["feature"].startswith("removed") and str(wt / "feature") in said["feature"]
    assert said["gone"].startswith("removed") and "was already gone" in said["gone"]
    assert said["plain"].startswith("removed") and "no worktree" in said["plain"]
    assert "Removed 3 branches" in result.text
    assert branches(repo) == {"main", "kept"}
    assert not (wt / "feature").exists() and (wt / "kept").exists()
    assert worktree_paths(repo) == {str(repo), str(wt / "kept")}
    tracking = run_git("for-each-ref", "--format=%(refname:short)", "refs/remotes", cwd=repo)
    assert {"origin/feature", "origin/gone", "origin/plain"} <= set(tracking.split())
    assert (repo / ".git" / "repocop" / "sessions" / "s1.jsonl").exists()
    now = run_git("rev-parse", "HEAD", cwd=repo), run_git("status", "--porcelain", cwd=repo)
    assert now == head  # the primary checkout is as it was
    assert client.get(REMOVE).status_code == 405  # a GET removes nothing


def test_removing_refuses_each_branch_whose_work_would_be_lost_and_removes_the_rest(
    registered: Path, client: TestClient, fake_gh: FakeGh, tmp_path: Path
) -> None:
    repo, wt = registered, tmp_path / "wt"
    merged(repo, fake_gh, "dirty", 1, worktree=wt / "dirty")
    (wt / "dirty" / "dirty.txt").write_text("changed\n")
    merged(repo, fake_gh, "untracked", 2, worktree=wt / "untracked")
    (wt / "untracked" / "notes.md").write_text("draft\n")
    merged(repo, fake_gh, "locked", 3, worktree=wt / "locked")
    run_git("worktree", "lock", "--reason", "in use", str(wt / "locked"), cwd=repo)
    merged(repo, fake_gh, "busy", 4, worktree=wt / "busy")
    record_session(repo, {"event": "turn-finished", "cwd": str(wt / "busy" / "src")}, session="s1")
    merged(repo, fake_gh, "moved", 6, worktree=wt / "moved")
    commit_on(wt / "moved", "late.txt")
    merged(repo, fake_gh, "fine", 7, worktree=wt / "fine")
    record_session(
        repo, {"event": "closed", "reason": "exit", "cwd": str(wt / "fine")}, session="s2"
    )
    merged(repo, fake_gh, "primary-work", 5)
    run_git("switch", "-q", "primary-work", cwd=repo)
    before = branches(repo), worktree_paths(repo)

    names = ["dirty", "untracked", "locked", "busy", "primary-work", "moved", "fine", "never"]
    result = client.post(REMOVE, data={"branch": names}).text
    said = outcomes(result)
    assert said["dirty"].startswith("refused") and "modified or untracked" in said["dirty"]
    assert "dirty.txt" in said["dirty"]
    assert said["untracked"].startswith("refused") and "notes.md" in said["untracked"]
    assert said["locked"].startswith("refused") and "locked" in said["locked"]
    assert "in use" in said["locked"]
    assert said["busy"].startswith("refused") and "session" in said["busy"] and "s1" in said["busy"]
    assert said["primary-work"].startswith("refused") and "primary checkout" in said["primary-work"]
    assert said["moved"].startswith("refused") and "isn&#39;t merged now" in said["moved"]
    assert said["never"].startswith("refused") and "isn&#39;t merged now" in said["never"]
    assert said["fine"].startswith("removed")
    assert "Removed 1 branch" in result and "7 refused" in result
    kept = before[0] - {"fine"}, before[1] - {str(wt / "fine")}
    assert (branches(repo), worktree_paths(repo)) == kept
    assert (wt / "dirty" / "dirty.txt").read_text() == "changed\n"
    assert (wt / "untracked" / "notes.md").exists() and (wt / "locked").exists()
    assert run_git("symbolic-ref", "--short", "HEAD", cwd=repo) == "primary-work"


def test_merged_branches_say_why_they_cant_be_read_and_the_rest_of_the_page_shows(
    registered: Path, client: TestClient, fake_gh: FakeGh, tmp_path: Path, remote_repo: Path
) -> None:
    merged(registered, fake_gh, "feature", 1, worktree=tmp_path / "wt" / "feature")
    add_requirement(registered, "todo-one.md")
    fake_gh.log_out()
    html = client.get(READ).text
    assert "the GitHub CLI isn&#39;t logged in to github.com" in listing(html)
    assert "Remove" not in listing(html)
    assert card(html, "todo-one")
    said = outcomes(client.post(REMOVE, data={"branch": ["feature"]}).text)
    assert said["feature"].startswith("refused") and "isn&#39;t logged in" in said["feature"]
    assert "feature" in branches(registered)

    form = {"remote_url": str(remote_repo), "name": "local", "default_branch": "main"}
    client.post("/repositories", data=form)
    local = client.get("/repositories/2?pull_requests=true").text
    assert "isn&#39;t a repository on github.com" in listing(local)


def test_merged_branches_say_when_only_the_newest_pull_requests_were_read(
    registered: Path, client: TestClient, fake_gh: FakeGh
) -> None:
    tip = run_git("rev-parse", "HEAD", cwd=registered)
    for number in range(1, 501):
        fake_gh.add_merged_pull_request(f"old-{number}", pull(number), tip)
    merged(registered, fake_gh, "feature", 501)  # the newest, so within what is read
    section = listing(client.get(READ).text)
    assert picked(section) == ["feature"]
    assert "only the newest 500 merged pull requests were read" in section


def test_merged_branches_are_read_with_a_fixed_number_of_git_calls(
    registered: Path,
    client: TestClient,
    fake_gh: FakeGh,
    tmp_path: Path,
    git_calls: Callable[[], list[list[str]]],
) -> None:
    merged(registered, fake_gh, "one", 1, worktree=tmp_path / "wt" / "one")
    before = len(git_calls())
    client.get("/board?repository=1")
    with_one = len(git_calls()) - before
    for number, name in enumerate(("two", "three", "four"), start=2):
        merged(registered, fake_gh, name, number, worktree=tmp_path / "wt" / name)
    before = len(git_calls())
    client.get("/board?repository=1")
    assert len(git_calls()) - before == with_one
