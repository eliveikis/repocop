"""Navigation every page shares: the quick switcher's matches for what was typed, and the session
lists a page shows, as they are now."""

import sys

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from repocop.routes.dependencies import ConnectionDep, SettingsDep
from repocop.services import navigation

router = APIRouter(prefix="/navigation")


@router.get("/matches", response_class=HTMLResponse)
def switcher_matches(
    request: Request, conn: ConnectionDep, settings: SettingsDep, q: str = ""
) -> HTMLResponse:
    """The switcher's options: what `q` finds, or nothing before anything is typed."""
    typed = bool(q.strip())
    context = {"query": q, "matches": navigation.search(conn, settings, q) if typed else None}
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "partials/matches.html", context)


@router.post("/sessions", response_class=HTMLResponse)
async def session_lists(
    request: Request, conn: ConnectionDep, settings: SettingsDep
) -> HTMLResponse:
    """The session lists named in the body's `shown` fields, and the sidebar's sessions that need
    input, as they are now, each to be swapped into the page where it stands. It changes nothing:
    the names come in the body, as a page shows one list per requirement however many there are,
    more than an address or a form's usual field count holds."""
    form = await request.form(max_fields=sys.maxsize)
    shown = [value for value in form.getlist("shown") if isinstance(value, str)]
    lists, waiting, standings = await run_in_threadpool(
        navigation.session_lists, conn, settings, shown
    )
    context = {"lists": lists, "needs_input": waiting, "standings": standings}
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "partials/session_lists.html", context)
