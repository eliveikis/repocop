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
from tests.conftest import Inbox, add_requirement, record_session, run_git
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
    html = client.get("/repositories/1").text
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
    page = sessions_in(client.get(PAGE).text, "p:1:bulk-import")
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
        r'<div hidden hx-post="([^"]+)" hx-trigger="every 2s" hx-swap="none" '
        r"hx-include=\"\[name='shown'\]\"></div>",
        html,
    )
    assert poll, "no refresh"
    record(registered, {"event": "waiting", "branch": "bulk-import", "waiting_for": "answer"})
    record(registered, {"event": "working", "branch": "spike"}, session="two")
    before = len(git_calls())
    shown = ["r:1:bulk-import", "p:1:bulk-import", "r:1:search", "o:1", "a:1", "r:999:x", "x"]
    fresh = client.post(poll[1], data={"shown": shown}).text
    assert len(git_calls()) == before
    for key in ("r:1:bulk-import", "p:1:bulk-import", "r:1:search", "o:1", "a:1"):
        assert re.search(
            rf'id="[^"]+" hx-swap-oob="true">\s*<input type="hidden" name="shown" '
            rf'value="{key}">',
            fresh,
        ), key
    assert "r:999:x" not in fresh and 'value="x"' not in fresh
    assert NEEDS_INPUT in sessions_in(fresh, "r:1:bulk-import")
    assert sessions_in(fresh, "r:1:search").strip() == ""
    assert "<code>spike</code>" in sessions_in(fresh, "o:1")
    assert '<div id="nav-sessions" hx-swap-oob="true">' in fresh
    fleet = [f"r:1:change-{number}" for number in range(2000)]  # as many as a big board shows
    lists = client.post(poll[1], data={"shown": fleet})
    assert lists.status_code == 200
    assert 'value="r:1:change-1999"' in lists.text


def test_a_repository_whose_default_branch_lacks_the_recorder_says_so(
    client: TestClient, registered: Path
) -> None:
    lacking = "lacks the hook that records agent sessions"
    assert lacking in client.get("/").text
    assert lacking in client.get("/repositories/1").text
    put_the_recorder_on_origin(registered)
    assert lacking not in client.get("/").text
    assert lacking not in client.get("/repositories/1").text


# ---------------------------------------------------------------- asking a session

REQUESTS = f"{PAGE}/sessions/one/requests"


@pytest.fixture
def skilled(registered: Path) -> Path:
    """The registered checkout with its `implement` and `review-requirement` skills committed."""
    for name in ("implement", "review-requirement"):
        (registered / ".claude" / "skills" / name).mkdir(parents=True)
        (registered / ".claude" / "skills" / name / "SKILL.md").write_text(f"# {name}\n")
    run_git("add", ".claude", cwd=registered)
    run_git("commit", "-qm", "Add skills", cwd=registered)
    return registered


def ask_section(html: str) -> str:
    found = re.search(r'<section id="ask".*?</section>', html, re.DOTALL)
    return found[0] if found else ""


def test_a_requirements_page_offers_each_live_session_its_committed_workflows_and_nothing_else(
    client: TestClient, skilled: Path, inbox_socket: Inbox
) -> None:
    on_it = {"branch": "bulk-import", "socket": str(inbox_socket.path)}
    record(skilled, {"event": "turn-finished", **on_it})
    record(skilled, {"event": "closed", "reason": "exit", **on_it}, session="two")
    record(skilled, {"event": "turn-finished", "branch": "bulk-import"}, session="three")
    asks = ask_section(client.get(PAGE).text)
    assert f'action="http://testserver{REQUESTS}"' in asks
    assert re.findall(r"<option>([^<]*)</option>", asks) == ["implement", "review-requirement"]
    assert "<textarea" not in asks and 'type="text"' not in asks  # no free text goes with it
    assert "sessions/two/" not in asks  # closed: not live
    assert "doesn&#39;t hand sessions requests yet" in asks  # three's template is older
    assert 'data-copy="/implement specs/changes/todo/bulk-import.md"' in asks


def test_asking_an_idle_session_hands_it_the_request_at_once_and_the_page_says_so(
    client: TestClient, skilled: Path, inbox_socket: Inbox
) -> None:
    record(
        skilled,
        {"event": "turn-finished", "branch": "bulk-import", "socket": str(inbox_socket.path)},
    )
    response = client.post(REQUESTS, data={"workflow": "implement"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    html = client.get(response.headers["location"]).text
    assert '<p class="toast">Asked the session to run implement.</p>' in html
    assert "Handed <code>implement</code>" in sessions_in(html, "p:1:bulk-import")
    [line] = inbox_socket.received()
    assert "run the `implement` skill with the argument" in line["message"]["content"]


def test_asking_a_working_session_leaves_a_request_that_waits_and_can_be_cancelled(
    client: TestClient, skilled: Path, inbox_socket: Inbox
) -> None:
    record(skilled, {"event": "working", "branch": "bulk-import", "socket": str(inbox_socket.path)})
    client.post(REQUESTS, data={"workflow": "review-requirement"})
    html = client.get(PAGE).text
    assert "it gets it when its turn ends" in sessions_in(html, "p:1:bulk-import")
    assert f'action="http://testserver{REQUESTS}/cancel"' in ask_section(html)
    cancelled = client.post(f"{REQUESTS}/cancel")
    assert '<p class="toast">Cancelled the request.</p>' in cancelled.text
    assert "turn ends" not in sessions_in(cancelled.text, "p:1:bulk-import")
    assert inbox_socket.received() == []


def test_a_request_is_refused_for_an_uncommitted_workflow_or_another_requirements_session(
    client: TestClient, skilled: Path, inbox_socket: Inbox
) -> None:
    record(
        skilled,
        {"event": "turn-finished", "branch": "bulk-import", "socket": str(inbox_socket.path)},
    )
    record(skilled, {"event": "turn-finished", "branch": "search"}, session="two")
    refused = client.post(REQUESTS, data={"workflow": "deploy"})
    assert refused.status_code == 400
    assert "isn&#39;t a skill committed" in refused.text
    elsewhere = client.post(f"{PAGE}/sessions/two/requests", data={"workflow": "implement"})
    assert elsewhere.status_code == 404
    assert inbox_socket.received() == []
