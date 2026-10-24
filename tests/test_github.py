"""GitHub service: which remotes are on GitHub, and driving the GitHub CLI without prompting."""

import shutil
from pathlib import Path

import pytest

from repocop.services import github
from tests.fakes.fake_gh import FakeGh

PULL = "https://github.com/owner/sample/pull/7"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/sample.git",
        "git@github.com:owner/sample.git",
        "ssh://git@GitHub.com/owner/sample",
    ],
)
def test_repository_of_names_the_owner_and_repository_of_a_github_remote(url: str) -> None:
    assert github.repository_of(url) == "owner/sample"


@pytest.mark.parametrize(
    "url",
    [
        "git@gitlab.com:owner/sample.git",
        "https://github.com.example.org/owner/sample.git",
        "https://github.com/owner/group/sample.git",
        "file:///srv/git/sample.git",
        "/srv/git/sample.git",
    ],
)
def test_repository_of_refuses_a_remote_that_is_not_on_github(url: str) -> None:
    with pytest.raises(github.GitHubError, match=r"isn't a repository on github\.com"):
        github.repository_of(url)


def test_check_ready_passes_when_gh_is_logged_in(fake_gh: FakeGh, tmp_path: Path) -> None:
    github.check_ready(tmp_path)
    assert fake_gh.calls == [["auth", "status", "--hostname", "github.com"]]


def test_check_ready_refuses_when_gh_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(github.GitHubError, match="isn't installed"):
        github.check_ready(tmp_path)


def test_check_ready_refuses_when_gh_is_logged_out(fake_gh: FakeGh, tmp_path: Path) -> None:
    fake_gh.log_out()
    with pytest.raises(github.GitHubError, match="gh auth login"):
        github.check_ready(tmp_path)


def test_gh_calls_fail_unless_a_test_asks_for_the_fake(tmp_path: Path) -> None:
    assert shutil.which("gh") == str(Path(__file__).parent / "fakes" / "bin" / "gh")
    with pytest.raises(github.GitHubError, match="never calls GitHub"):
        github.pull_request_of(tmp_path, "owner/sample", "feature/req-1-x")


def test_create_pull_request_returns_its_url(fake_gh: FakeGh, tmp_path: Path) -> None:
    url = github.create_pull_request(
        tmp_path, "owner/sample", head="feature/req-1-x", base="main", title="-t", body="Body"
    )
    assert url == "https://github.com/owner/sample/pull/1"
    expected = ["pr", "create", "--repo", "owner/sample", "--head", "feature/req-1-x"]
    expected += ["--base", "main", "--title", "-t", "--body", "Body"]
    assert fake_gh.calls == [expected]


def test_gh_runs_in_the_given_folder_and_never_prompts(fake_gh: FakeGh, tmp_path: Path) -> None:
    github.pull_request_of(tmp_path, "owner/sample", "feature/req-1-x")
    assert fake_gh.records[0]["cwd"] == str(tmp_path)
    assert fake_gh.records[0]["prompt_disabled"] == "1"


def test_pull_request_of_finds_a_branchs_open_pull_request(fake_gh: FakeGh, tmp_path: Path) -> None:
    assert github.pull_request_of(tmp_path, "owner/sample", "feature/req-1-x") is None
    fake_gh.add_pull_request("feature/req-1-x", PULL)
    assert github.pull_request_of(tmp_path, "owner/sample", "feature/req-1-x") == PULL
    listed = ["pr", "list", "--repo", "owner/sample", "--head", "feature/req-1-x"]
    assert fake_gh.calls[0] == [*listed, "--state", "open", "--json", "url", "--limit", "1"]


def test_request_copilot_review_adds_copilot_as_a_reviewer(fake_gh: FakeGh, tmp_path: Path) -> None:
    github.request_copilot_review(tmp_path, PULL)
    assert fake_gh.calls == [["pr", "edit", PULL, "--add-reviewer", "@copilot"]]


def test_a_failed_gh_command_reports_its_reason(fake_gh: FakeGh, tmp_path: Path) -> None:
    fake_gh.fail_with("GraphQL: Resource not accessible by integration")
    with pytest.raises(github.GitHubError, match="gh pr edit failed: GraphQL: Resource not"):
        github.request_copilot_review(tmp_path, PULL)


def test_create_pull_request_refuses_output_that_is_not_a_pull_request_url(
    fake_gh: FakeGh, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github, "HOST", "github.example")
    with pytest.raises(github.GitHubError, match="didn't give the pull request's address"):
        github.create_pull_request(
            tmp_path, "owner/sample", head="feature/req-1-x", base="main", title="T", body="B"
        )
