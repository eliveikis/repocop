"""Task pages: details, transcript and worktree (each refreshing while the task is active),
instructions, cancel, done, starting again, and a template sync's pull request."""

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.routes.dependencies import ConnectionDep, RunnerDep, SettingsDep, TaskDep
from repocop.services import pull_requests, repositories, requirements, reviews, tasks
from repocop.services.tasks import Task
from repocop.services.worktrees import Changes

router = APIRouter()


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_page(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    task: TaskDep,
    started: bool = False,
    cancelled: bool = False,
    sent: bool = False,
    done: bool = False,
    pull_request: pull_requests.Action | None = None,
) -> HTMLResponse:
    notices = {"started": started, "cancelled": cancelled, "sent": sent, "done": done}
    return _render_task(
        request, conn, settings, task, notices=notices, pull_request_done=pull_request
    )


@router.get("/tasks/{task_id}/header", response_class=HTMLResponse)
def task_header(
    request: Request, conn: ConnectionDep, settings: SettingsDep, task: TaskDep
) -> HTMLResponse:
    context = _details(conn, settings, task)
    return _templates(request).TemplateResponse(request, "partials/task_header.html", context)


@router.get("/tasks/{task_id}/events", response_class=HTMLResponse)
def task_events(
    request: Request, conn: ConnectionDep, task: TaskDep, after: int = 0
) -> HTMLResponse:
    events = tasks.events_after(conn, task.id, after)
    context = {
        "task": task,
        "active": task.status in tasks.ACTIVE,
        "events": events,
        "last_seq": events[-1].seq if events else after,
    }
    return _templates(request).TemplateResponse(request, "partials/task_events.html", context)


@router.get("/tasks/{task_id}/worktree", response_class=HTMLResponse)
def task_worktree(
    request: Request, conn: ConnectionDep, settings: SettingsDep, task: TaskDep
) -> HTMLResponse:
    context = {
        "task": task,
        "active": task.status in tasks.ACTIVE,
        "changes": _changes(conn, settings, task),
    }
    return _templates(request).TemplateResponse(request, "partials/task_worktree.html", context)


@router.post("/tasks/{task_id}/instructions", response_class=HTMLResponse)
async def send_instruction(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    task: TaskDep,
    runner: RunnerDep,
    text: Annotated[str, Form()] = "",
) -> Response:
    try:
        await runner.send(task.id, text)
    except RepoCopError as exc:
        return await run_in_threadpool(
            _render_task,
            request,
            conn,
            settings,
            task,
            error=str(exc),
            instruction=text,
            status_code=400,
        )
    return _back_to(request, task, sent="true")


@router.post("/tasks/{task_id}/cancel", response_class=HTMLResponse)
async def cancel_task(
    request: Request, conn: ConnectionDep, settings: SettingsDep, task: TaskDep, runner: RunnerDep
) -> Response:
    try:
        await runner.cancel(task.id)
    except RepoCopError as exc:
        return await run_in_threadpool(
            _render_task, request, conn, settings, task, error=str(exc), status_code=400
        )
    return _back_to(request, task, cancelled="true")


@router.post("/tasks/{task_id}/again", response_class=HTMLResponse)
async def start_task_again(
    request: Request, conn: ConnectionDep, settings: SettingsDep, task: TaskDep, runner: RunnerDep
) -> Response:
    try:
        again = await run_in_threadpool(tasks.start_again, conn, settings, task)
    except RepoCopError as exc:
        return await run_in_threadpool(
            _render_task, request, conn, settings, task, error=str(exc), status_code=400
        )
    runner.run(again.id)
    return _back_to(request, again, started="true")


@router.post("/tasks/{task_id}/done", response_class=HTMLResponse)
def mark_task_done(
    request: Request, conn: ConnectionDep, settings: SettingsDep, task: TaskDep
) -> Response:
    try:
        tasks.mark_done(conn, task)
    except RepoCopError as exc:
        return _render_task(request, conn, settings, task, error=str(exc), status_code=400)
    return _back_to(request, task, done="true")


@router.post("/tasks/{task_id}/pull-request/{action}", response_class=HTMLResponse)
def task_pull_request(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    task: TaskDep,
    action: pull_requests.Action,
) -> Response:
    try:
        source = pull_requests.of_sync(conn, settings, task)
        done = pull_requests.perform(conn, settings, source, action)
    except RepoCopError as exc:
        return _render_task(request, conn, settings, task, error=str(exc), status_code=400)
    if action is pull_requests.Action.OPEN:  # the new pull request, on GitHub
        return RedirectResponse(done.url, status_code=303)
    return _back_to(request, task, pull_request=action.value)


def _back_to(request: Request, task: Task, **notice: str) -> RedirectResponse:
    target = request.url_for("task_page", task_id=task.id).include_query_params(**notice)
    return RedirectResponse(target, status_code=303)


def _templates(request: Request) -> Jinja2Templates:
    templates: Jinja2Templates = request.app.state.templates
    return templates


def _details(conn: sqlite3.Connection, settings: Settings, task: Task) -> dict[str, Any]:
    """What the task header shows: the task, where it belongs, how it was interrupted, how to
    continue its session in a terminal, and the link that opens its worktree in the editor."""
    worktree = tasks.worktree(conn, settings, task) if settings.editor_url else None
    return {
        "task": task,
        "active": task.status in tasks.ACTIVE,
        "repository": repositories.get(conn, task.repository_id),
        "requirement": requirements.get(conn, task.requirement_id) if task.requirement_id else None,
        "interruption": tasks.interruption(conn, task.id),
        "resume_command": tasks.resume_command(conn, settings, task),
        "editor_link": settings.editor_link(worktree) if worktree else None,
    }


def _pull_request(conn: sqlite3.Connection, task: Task) -> pull_requests.PullRequest | None:
    return pull_requests.get(conn, task.repository_id, task.branch) if task.branch else None


def _changes(conn: sqlite3.Connection, settings: Settings, task: Task) -> Changes | None:
    try:
        return tasks.worktree_changes(conn, settings, task)
    except RepoCopError:
        return None


def _render_task(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    task: Task,
    *,
    notices: dict[str, bool] | None = None,
    pull_request_done: pull_requests.Action | None = None,
    error: str | None = None,
    instruction: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    current = tasks.get(conn, task.id) or task
    events = tasks.events_after(conn, current.id, 0)
    offered = pull_requests.has_own(current) and current.branch is not None
    context = _details(conn, settings, current) | {
        "events": events,
        "last_seq": events[-1].seq if events else 0,
        "changes": _changes(conn, settings, current),
        "notices": notices or {},
        "pull_request_offered": offered,
        "pull_request": _pull_request(conn, current) if offered else None,
        "pull_request_done": pull_request_done,
        "error": error,
        "instruction": instruction,
        "instructable": not reviews.is_review(current),
    }
    return _templates(request).TemplateResponse(
        request, "tasks/show.html", context, status_code=status_code
    )
