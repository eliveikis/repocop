"""Requirement pages: show a requirement read-only, with its sessions and the line that runs each
workflow on it in the developer's own agent, and ask one of its live sessions to run a workflow
on it. A requirement's page is found by its repository and its file name."""

import sqlite3
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.routes.dependencies import ConnectionDep, RequirementDep, SettingsDep
from repocop.services import backlog, repositories, requirements, session_requests, sessions, tasks
from repocop.services.repositories import Repository
from repocop.services.requirements import Location, Requirement
from repocop.services.sessions import Session

router = APIRouter()
# A requirement's page, named by its repository and its file.
REQUIREMENT_PATH = "/repositories/{repository_id}/requirements/{file_name:file}"
# What one of its sessions is asked, named by the session's id.
REQUESTS_PATH = REQUIREMENT_PATH + "/sessions/{session_id}/requests"


@router.get(REQUIREMENT_PATH, response_class=HTMLResponse)
def requirement_page(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    asked: str | None = None,
    cancelled: bool = False,
) -> HTMLResponse:
    notice = None
    if asked:
        notice = f"Asked the session to run {asked}."
    elif cancelled:
        notice = "Cancelled the request."
    return _render(request, conn, settings, requirement, notice=notice)


@router.post(REQUESTS_PATH, response_class=HTMLResponse)
def ask_session(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    session_id: str,
    workflow: Annotated[str, Form()] = "",
) -> Response:
    repository, session = _session_of(conn, settings, requirement, session_id)
    try:
        session_requests.send(repository, settings, session, workflow, requirement.path)
    except RepoCopError as exc:
        return _render(request, conn, settings, requirement, error=str(exc), status_code=400)
    return _back(request, requirement, asked=workflow)


@router.post(REQUESTS_PATH + "/send", response_class=HTMLResponse)
def send_waiting_request(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    session_id: str,
) -> Response:
    repository, session = _session_of(conn, settings, requirement, session_id)
    try:
        sent = session_requests.send_waiting(repository, settings, session)
    except RepoCopError as exc:
        return _render(request, conn, settings, requirement, error=str(exc), status_code=400)
    return _back(request, requirement, asked=sent.workflow)


@router.post(REQUESTS_PATH + "/cancel", response_class=HTMLResponse)
def cancel_request(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    session_id: str,
) -> Response:
    repository, session = _session_of(conn, settings, requirement, session_id)
    try:
        session_requests.cancel(repository, settings, session)
    except RepoCopError as exc:
        return _render(request, conn, settings, requirement, error=str(exc), status_code=400)
    return _back(request, requirement, cancelled="true")


def _repository_of(conn: sqlite3.Connection, requirement: Requirement) -> Repository:
    repository = repositories.get(conn, requirement.repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return repository


def _session_of(
    conn: sqlite3.Connection, settings: Settings, requirement: Requirement, session_id: str
) -> tuple[Repository, Session]:
    """The requirement's repository, and its session `session_id`, or 404."""
    repository = _repository_of(conn, requirement)
    session = sessions.get(repository, settings, session_id)
    if session is None or session.requirement != backlog.name_of(requirement.file_name):
        raise HTTPException(status_code=404, detail="no such session works on this requirement")
    return repository, session


def _back(request: Request, requirement: Requirement, **notice: str) -> RedirectResponse:
    page = request.url_for(
        "requirement_page",
        repository_id=requirement.repository_id,
        file_name=requirement.file_name,
    )
    return RedirectResponse(page.include_query_params(**notice), status_code=303)


def _render(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    *,
    notice: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    repository = _repository_of(conn, requirement)
    detail = None
    workflows: list[str] = []
    change = None
    ordered = None
    try:
        detail = requirements.detail(settings, repository, requirement)
        workflows = tasks.workflows(settings, repository)
        ordered = backlog.of(settings, repository)
        file = PurePosixPath(requirement.path).name
        change = ordered.change(file)
        if change is None and detail.location is Location.ARCHIVED and detail.content:
            change = ordered.delivered_change(file, detail.content.body)
    except RepoCopError as exc:
        error = error or str(exc)
    shown = detail.content if detail else None
    name = backlog.name_of(requirement.file_name)
    working = sessions.for_requirement(sessions.of(repository, settings), name)
    standings = {s.id: session_requests.standing(repository, settings, s) for s in working}
    context: dict[str, Any] = {
        "repository": repository,
        "requirement": requirement,
        "detail": detail,
        "editor_link": (
            settings.editor_link(repository.primary_path / shown.path, file=True) if shown else None
        ),
        "workflows": workflows,
        "workflow_lines": [
            tasks.workflow_line(workflow, requirement.path) for workflow in workflows
        ],
        "notice": notice,
        "error": error,
        "card_name": name,
        "sessions": working,
        "standings": standings,
        "asks": [
            (session, session_requests.unreachable(session), standings[session.id])
            for session in working
            if session.live
        ],
        "change": change,
        "blocks": ordered.blocks(change) if ordered and change else (),
        "change_problems": ordered.problems_of(change) if ordered and change else (),
        "pages": ordered.pages if ordered else {},
    }
    return templates.TemplateResponse(
        request, "requirements/show.html", context, status_code=status_code
    )
