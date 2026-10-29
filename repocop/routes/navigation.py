"""Navigation every page shares: the quick switcher's matches for what was typed, and the session
lists a page shows, as they are now."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from repocop.routes.dependencies import ConnectionDep, SettingsDep
from repocop.services import navigation

router = APIRouter(prefix="/navigation")
SESSION_LISTS_READ = 500  # the most session lists one page asks for


@router.get("/matches", response_class=HTMLResponse)
def switcher_matches(
    request: Request, conn: ConnectionDep, settings: SettingsDep, q: str = ""
) -> HTMLResponse:
    """The switcher's options: what `q` finds, or nothing before anything is typed."""
    typed = bool(q.strip())
    context = {"query": q, "matches": navigation.search(conn, settings, q) if typed else None}
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "partials/matches.html", context)


@router.get("/sessions", response_class=HTMLResponse)
def session_lists(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    shown: Annotated[list[str] | None, Query(max_length=SESSION_LISTS_READ)] = None,
) -> HTMLResponse:
    """The session lists named in `shown`, and the sidebar's sessions that need input, as they
    are now, each to be swapped into the page where it stands."""
    lists, waiting, standings = navigation.session_lists(conn, settings, shown or [])
    context = {"lists": lists, "needs_input": waiting, "standings": standings}
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "partials/session_lists.html", context)
