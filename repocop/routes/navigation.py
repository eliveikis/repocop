"""Navigation every page shares: the quick switcher's matches for what was typed."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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
