"""Requirement pages: create a requirement in a repository, then view, edit and commit it, start
tasks on it, have its branch reviewed, and act on its branch's pull request. A requirement's
pages are found by its repository and its file name."""

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
    RepositoryDep,
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

router = APIRouter()
# A requirement's page, named by its repository and its file.
REQUIREMENT_PATH = "/repositories/{repository_id}/requirements/{file_name:file}"

FormField = Annotated[str, Form()]


@router.get("/repositories/{repository_id}/requirements/new", response_class=HTMLResponse)
def new_requirement_page(request: Request, repository: RepositoryDep) -> HTMLResponse:
    return _render_new(request, repository)


@router.post("/repositories/{repository_id}/requirements", response_class=HTMLResponse)
def create_requirement(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    repository: RepositoryDep,
    name: FormField = "",
    kind: FormField = "feature",
    body: FormField = "",
) -> Response:
    try:
        saved = requirements.create(conn, settings, repository, name=name, body=body, kind=kind)
    except RepoCopError as exc:
        form = {"name": name, "kind": kind, "body": body}
        return _render_new(request, repository, form=form, error=str(exc), status_code=400)
    return _redirect(
        request, saved.requirement, saved="committed" if saved.committed else "uncommitted"
    )


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
    saved: str | None = None,
    committed: bool = False,
    pull_request: pull_requests.Action | None = None,
) -> HTMLResponse:
    return _render_requirement(
        request,
        conn,
        settings,
        requirement,
        saved=saved,
        committed=committed,
        pull_request_done=pull_request,
    )


@router.post(REQUIREMENT_PATH, response_class=HTMLResponse)
def save_requirement(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    requirement: RequirementDep,
    kind: FormField = "feature",
    body: FormField = "",
    version: FormField = "",
) -> Response:
    repository = _repository_of(conn, requirement)
    try:
        saved = requirements.update(
            conn,
            settings,
            repository,
            requirement,
            body=body,
            kind=kind,
            version=version,
        )
    except RepoCopError as exc:
        form = {"kind": kind, "body": body, "version": version}
        return _render_requirement(
            request, conn, settings, requirement, form=form, error=str(exc), status_code=400
        )
    return _redirect(
        request, saved.requirement, saved="committed" if saved.committed else "uncommitted"
    )


@router.post(REQUIREMENT_PATH + "/commit", response_class=HTMLResponse)
def commit_requirement(
    request: Request, conn: ConnectionDep, settings: SettingsDep, requirement: RequirementDep
) -> Response:
    try:
        requirements.commit(settings, _repository_of(conn, requirement), requirement)
    except RepoCopError as exc:
        return _render_requirement(
            request, conn, settings, requirement, error=str(exc), status_code=400
        )
    return _redirect(request, requirement, committed="true")


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
    return _redirect(request, requirement, pull_request=action.value)


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


def _redirect(request: Request, requirement: Requirement, **params: str) -> RedirectResponse:
    target = _page(request, requirement).include_query_params(**params)
    return RedirectResponse(target, status_code=303)


def _render_new(
    request: Request,
    repository: Repository,
    *,
    form: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    context = {
        "repository": repository,
        "todo_dir": requirements.todo_dir(repository),
        "form": form or {"name": "", "kind": "feature", "body": ""},
        "error": error,
    }
    return templates.TemplateResponse(
        request, "requirements/new.html", context, status_code=status_code
    )


def _render_requirement(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    requirement: Requirement,
    *,
    form: dict[str, str] | None = None,
    error: str | None = None,
    saved: str | None = None,
    committed: bool = False,
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
    if form is None and detail is not None and detail.content is not None:
        form = {
            "kind": requirement.kind.value,
            "body": detail.content.body,
            "version": detail.content.version,
        }
    context = {
        "repository": repository,
        "requirement": requirement,
        "detail": detail,
        "tasks": tasks.list_for_requirement(conn, requirement),
        "workflows": workflows,
        "form": form,
        "error": error,
        "saved": saved,
        "committed": committed,
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
