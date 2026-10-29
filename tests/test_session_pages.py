"""Sessions on RepoCop's pages: on the board's cards and under their repository, on requirement
and repository pages, in the sidebar when they need input, and as they change, read at little
cost."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from repocop.config import Settings
from tests.conftest import add_requirement, record_session, run_git
from tests.test_board import card, columns

HOOK = ".claude/hooks/session-events.sh"
PAGE = "/repositories/1/requirements/bulk-import.md"
WORKING = '<span class="status status-working">Working</span>'
NEEDS_INPUT = '<span class="status status-needs-input">Needs input</span>'


def checkout(settings: Settings) -> Path:
    return settings.repos_root / "sample"


@pytest.fixture
def registered(client: TestClient, settings: Settings, remote_repo: Path) -> Path:
    """Repository `sample` with bulk-import and search to do, and its checkout."""
    client.post("/repositories", data={"remote_url": str(remote_repo), "default_branch": "main"})
    add_requirement(checkout(settings), "bulk-import.md")
    add_requirement(checkout(settings), "search.md")
    return checkout(settings)


def record(repo: Path, *events: dict[str, Any], session: str = "one") -> None:
    record_session(repo, *events, session=session)


def sessions_in(html: str, key: str) -> str:
    """The session list a page shows under `key`."""
    found = re.search(
        rf'<div class="sessions" id="[^"]+"[^>]*>\s*<input type="hidden" name="shown" '
        rf'value="{re.escape(key)}">(.*?)</div>',
        html,
        re.DOTALL,
    )
    assert found, f"no session list {key}"
    return found[1]


def sidebar(html: str) -> str:
    found = re.search(r'<nav id="sidebar".*?</nav>', html, re.DOTALL)
    assert found
    return found[0]


def put_the_recorder_on_origin(repo: Path) -> None:
    hook = repo / HOOK
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n")
    settings = '{"hooks": {"Stop": [{"hooks": [{"command": "' + HOOK + '"}]}]}}\n'
    (repo / ".claude" / "settings.json").write_text(settings)
    run_git("add", ".claude", cwd=repo)
    run_git("commit", "-qm", "Record sessions", cwd=repo)
    run_git("push", "-q", "origin", "main", cwd=repo)


def test_a_card_shows_its_sessions_and_a_live_one_puts_it_in_progress(
    client: TestClient, registered: Path
) -> None:
    record(
        registered,
        {
            "event": "workflow",
            "ago": 4,
            "workflow": "implement",
            "argument": "specs/changes/todo/bulk-import.md",
        },
    )
    record(registered, {"event": "closed", "branch": "search", "reason": "exit"}, session="two")
    html = client.get("/").text
    assert columns(html)["in-progress"] == ["bulk-import"]
    assert columns(html)["to-do"] == ["search"]  # a closed session isn't work going on
    on_card = sessions_in(card(html, "bulk-import"), "r:1:bulk-import")
    assert WORKING in on_card
    assert "<code>implement</code>" in on_card
    assert "Closed</span>: it exited" in sessions_in(card(html, "search"), "r:1:search")


def test_a_session_on_no_requirement_shows_under_its_repository(
    client: TestClient, registered: Path
) -> None:
    record(registered, {"event": "turn-finished", "branch": "spike/try-a-thing"})
    record(registered, {"event": "turn-finished", "branch": "agent/bulk-import"}, session="two")
    html = client.get("/").text
    others = sessions_in(html, "o:1")
    assert "Other sessions" in others
    assert "<code>spike/try-a-thing</code>" in others
    assert "agent/bulk-import" not in others  # it shows on bulk-import's card
    assert "Waiting for instruction" in sessions_in(card(html, "bulk-import"), "r:1:bulk-import")


def test_requirement_and_repository_pages_show_their_sessions_escaped(
    client: TestClient, registered: Path
) -> None:
    record(
        registered,
        {
            "event": "waiting",
            "branch": "bulk-import",
            "waiting_for": "permission",
            "tool": "<script>x</script>",
        },
    )
    record(registered, {"event": "working", "branch": "elsewhere"}, session="two")
    page = sessions_in(client.get(PAGE).text, "r:1:bulk-import")
    assert NEEDS_INPUT + ": permission to use <code>&lt;script&gt;x&lt;/script&gt;</code>" in page
    assert "elsewhere" not in page
    everyone = sessions_in(client.get("/repositories/1").text, "a:1")
    assert f'<a href="http://testserver{PAGE}">bulk-import</a>' in everyone
    assert "<code>elsewhere</code>" in everyone
    assert "<script>x</script>" not in everyone


def test_the_sidebar_lists_the_sessions_that_need_input_on_every_page(
    client: TestClient, registered: Path
) -> None:
    record(registered, {"event": "waiting", "branch": "bulk-import", "waiting_for": "answer"})
    record(registered, {"event": "working", "branch": "search"}, session="two")
    for address in ("/", "/repositories/1", PAGE):
        nav = sidebar(client.get(address).text)
        assert "Needs input" in nav, address
        assert f'href="http://testserver{PAGE}"' in nav
        assert "sample · a question" in nav
        assert "search" not in nav


def test_every_page_keeps_its_sessions_current_and_the_refresh_runs_no_git(
    client: TestClient, registered: Path, git_calls: Callable[[], list[list[str]]]
) -> None:
    html = client.get("/").text  # each repository's log folder is known from here on
    poll = re.search(
        r'<div hidden hx-get="([^"]+)" hx-trigger="every 2s" hx-swap="none" '
        r"hx-include=\"\[name='shown'\]\"></div>",
        html,
    )
    assert poll, "no refresh"
    record(registered, {"event": "waiting", "branch": "bulk-import", "waiting_for": "answer"})
    record(registered, {"event": "working", "branch": "spike"}, session="two")
    before = len(git_calls())
    shown = ["r:1:bulk-import", "r:1:search", "o:1", "a:1", "r:999:x", "nonsense"]
    fresh = client.get(poll[1], params={"shown": shown}).text
    assert len(git_calls()) == before
    for key in ("r:1:bulk-import", "r:1:search", "o:1", "a:1"):
        assert re.search(
            rf'id="[^"]+" hx-swap-oob="true">\s*<input type="hidden" name="shown" '
            rf'value="{key}">',
            fresh,
        ), key
    assert "r:999:x" not in fresh and "nonsense" not in fresh
    assert NEEDS_INPUT in sessions_in(fresh, "r:1:bulk-import")
    assert sessions_in(fresh, "r:1:search").strip() == ""
    assert "<code>spike</code>" in sessions_in(fresh, "o:1")
    assert '<div id="nav-sessions" hx-swap-oob="true">' in fresh


def test_a_repository_whose_default_branch_lacks_the_recorder_says_so(
    client: TestClient, registered: Path
) -> None:
    lacking = "lacks the hook that records agent sessions"
    assert lacking in client.get("/").text
    assert lacking in client.get("/repositories/1").text
    put_the_recorder_on_origin(registered)
    assert lacking not in client.get("/").text
    assert lacking not in client.get("/repositories/1").text
