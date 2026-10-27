"""Requirement pages: show a requirement read-only, with the line that runs each workflow on it,
start tasks on it, have its branch reviewed, and act on its branch's pull request. A
requirement's pages are found by its repository and its file name."""

import sqlite3
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import URL

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.routes.dependencies import (
    ConnectionDep,
    RequirementDep,
    RunnerDep,
    SettingsDep,
)
from repocop.services import (
    backlog,
    pull_requests,
    repositories,
    requirements,
    reviews,
    tasks,
)
from repocop.services.repositories import Repository
from repocop.services.requirements import Location, Requirement
from repocop.services.runner import workflow_prompt

router = APIRouter()
# A requirement's page, named by its repository and its file.
REQUIREMENT_PATH = "/repositories/{repository_id}/requirements/{file_name:file}"

FormField = Annotated[str, Form()]


@router.get("/requirements/{requirement_id}")
def recorded_requirement(
    request: Request, conn: ConnectionDep, requirement_id: int
) -> RedirectResponse:
    """The page of the requirement the database records under `requirement_id`."""
    requirement = requirements.get(conn, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="requirement not found")
    return RedirectResponse(_page(request, requirement))


@router.get(REQUIREMENT_PATH, response_class=HTMLResponse)
def requirement_page(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    pull_request: pull_requests.Action | None = None,
) -> HTMLResponse:
    return _render_requirement(request, conn, settings, requirement, pull_request_done=pull_request)


@router.post(REQUIREMENT_PATH + "/tasks", response_class=HTMLResponse)
async def start_task(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    runner: RunnerDep,
    workflow: FormField = "",
) -> Response:
    try:
        task = await run_in_threadpool(tasks.start, conn, settings, requirement, workflow)
    except RepoCopError as exc:
        return await run_in_threadpool(
            _render_requirement,
            request,
            conn,
            settings,
            requirement,
            error=str(exc),
            status_code=400,
        )
    runner.run(task.id)
    target = request.url_for("task_page", task_id=task.id).include_query_params(started="true")
    return RedirectResponse(target, status_code=303)


@router.post(REQUIREMENT_PATH + "/review", response_class=HTMLResponse)
async def start_review(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    runner: RunnerDep,
) -> Response:
    try:
        task = await run_in_threadpool(reviews.start, conn, settings, requirement)
    except RepoCopError as exc:
        return await run_in_threadpool(
            _render_requirement,
            request,
            conn,
            settings,
            requirement,
            error=str(exc),
            status_code=400,
        )
    runner.run(task.id)
    target = request.url_for("task_page", task_id=task.id).include_query_params(started="true")
    return RedirectResponse(target, status_code=303)


@router.post(
    REQUIREMENT_PATH + "/review/address",
    response_class=HTMLResponse,
)
async def address_review(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    runner: RunnerDep,
) -> Response:
    try:
        task = await run_in_threadpool(reviews.address, conn, settings, requirement)
    except RepoCopError as exc:
        return await run_in_threadpool(
            _render_requirement,
            request,
            conn,
            settings,
            requirement,
            error=str(exc),
            status_code=400,
        )
    runner.run(task.id)
    target = request.url_for("task_page", task_id=task.id).include_query_params(started="true")
    return RedirectResponse(target, status_code=303)


@router.post(
    REQUIREMENT_PATH + "/pull-request/{action}",
    response_class=HTMLResponse,
)
def requirement_pull_request(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    action: pull_requests.Action,
) -> Response:
    try:
        source = pull_requests.of_requirement(conn, settings, requirement)
        done = pull_requests.perform(conn, settings, source, action)
    except RepoCopError as exc:
        return _render_requirement(
            request, conn, settings, requirement, error=str(exc), status_code=400
        )
    if action is pull_requests.Action.OPEN:  # the new pull request, on GitHub
        return RedirectResponse(done.url, status_code=303)
    target = _page(request, requirement).include_query_params(pull_request=action.value)
    return RedirectResponse(target, status_code=303)


def _repository_of(conn: sqlite3.Connection, requirement: Requirement) -> Repository:
    repository = repositories.get(conn, requirement.repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return repository


def _page(request: Request, requirement: Requirement) -> URL:
    return request.url_for(
        "requirement_page",
        repository_id=requirement.repository_id,
        file_name=requirement.file_name,
    )


def _render_requirement(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    *,
    error: str | None = None,
    pull_request_done: pull_requests.Action | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    repository = _repository_of(conn, requirement)
    latest = tasks.last_with_worktree(conn, requirement)
    branch = latest.branch if latest else None
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
    context = {
        "repository": repository,
        "requirement": requirement,
        "detail": detail,
        "editor_link": (
            settings.editor_link(repository.primary_path / shown.path, file=True) if shown else None
        ),
        "tasks": tasks.list_for_requirement(conn, requirement),
        "workflows": workflows,
        "workflow_lines": [workflow_prompt(workflow, requirement.path) for workflow in workflows],
        "error": error,
        "branch": branch,
        "review": reviews.latest(conn, settings, requirement) if branch else None,
        "reviewer": reviews.REVIEWER,
        "review_base": reviews.base_of(repository),
        "pull_request": pull_requests.get(conn, repository.id, branch) if branch else None,
        "pull_request_done": pull_request_done,
        "change": change,
        "blocks": ordered.blocks(change) if ordered and change else (),
        "change_problems": ordered.problems_of(change) if ordered and change else (),
        "pages": ordered.pages if ordered else {},
    }
    return templates.TemplateResponse(
        request, "requirements/show.html", context, status_code=status_code
    )
