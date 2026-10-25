"""Template sync pages: the plan for a repository, and applying the picked files."""

import sqlite3
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.routes.dependencies import ConnectionDep, RepositoryDep, SettingsDep
from repocop.services import pull_requests, repositories, template_sync
from repocop.services.repositories import Repository

router = APIRouter()

Picks = Annotated[list[str] | None, Form()]


@router.get("/repositories/{repository_id}/sync", response_class=HTMLResponse)
def template_sync_page(
    request: Request, conn: ConnectionDep, settings: SettingsDep, repository: RepositoryDep
) -> HTMLResponse:
    return _render(request, conn, settings, repository)


@router.post("/repositories/{repository_id}/sync", response_class=HTMLResponse)
def apply_template_sync(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    repository: RepositoryDep,
    create: Picks = None,
    overwrite: Picks = None,
    merge: Picks = None,
    delete: Picks = None,
) -> Response:
    try:
        task = template_sync.apply(
            conn,
            settings,
            repository,
            create=create or [],
            overwrite=overwrite or [],
            merge=merge or [],
            delete=delete or [],
        )
    except RepoCopError as exc:
        return _render(request, conn, settings, repository, error=str(exc), status_code=400)
    if task is None:
        notice = "Nothing was picked, so nothing changed and no branch was created."
        return _render(request, conn, settings, repository, notice=notice)
    return RedirectResponse(request.url_for("task_page", task_id=task.id), status_code=303)


def _render(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    *,
    notice: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    plan = None
    try:
        plan = repositories.template_plan(repository, settings)
    except RepoCopError as exc:
        error = error or str(exc)
    waiting = template_sync.waiting(conn, settings, repository)
    context = {
        "repository": repository,
        "settings": settings,
        "plan": plan,
        "waiting": waiting,
        "waiting_ref": repositories.origin_default(repository),
        "waiting_pull_request": (
            pull_requests.get(conn, repository.id, waiting.branch)
            if waiting and waiting.branch
            else None
        ),
        "fetched_at": _last_fetch(repository, settings) if waiting else None,
        "notice": notice,
        "error": error,
    }
    return templates.TemplateResponse(
        request, "repositories/sync.html", context, status_code=status_code
    )


def _last_fetch(repository: Repository, settings: Settings) -> datetime | None:
    """When the checkout last fetched, or None if it never has or can't be read."""
    try:
        return repositories.last_fetch(repository, settings)
    except RepoCopError:
        return None
