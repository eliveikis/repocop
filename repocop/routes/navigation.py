"""Navigation every page shares: the sidebar's active tasks, which refresh while any is active,
and the quick switcher's matches for what was typed."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from repocop.routes.dependencies import ConnectionDep, SettingsDep
from repocop.services import navigation

router = APIRouter(prefix="/navigation")


@router.get("/active-tasks", response_class=HTMLResponse)
def active_tasks_panel(request: Request, conn: ConnectionDep) -> HTMLResponse:
    context = {"active_tasks": navigation.active_tasks(conn)}
    return _templates(request).TemplateResponse(request, "partials/active_tasks.html", context)


@router.get("/matches", response_class=HTMLResponse)
def switcher_matches(
    request: Request, conn: ConnectionDep, settings: SettingsDep, q: str = ""
) -> HTMLResponse:
    """The switcher's options: the active tasks before anything is typed, else what `q` finds."""
    typed = bool(q.strip())
    context = {
        "query": q,
        "matches": navigation.search(conn, settings, q) if typed else None,
        "active_tasks": [] if typed else navigation.active_tasks(conn),
    }
    return _templates(request).TemplateResponse(request, "partials/matches.html", context)


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates
