"""Template sync pages: what a sync did, its worktree, and its pull request."""

import sqlite3
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.routes.dependencies import ConnectionDep, SettingsDep, TaskDep
from repocop.services import pull_requests, repositories, tasks, template_sync
from repocop.services.tasks import Status, Task

router = APIRouter()


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_page(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    task: TaskDep,
    pull_request: pull_requests.Action | None = None,
) -> HTMLResponse:
    return _render_task(request, conn, settings, task, pull_request_done=pull_request)


@router.post("/tasks/{task_id}/pull-request/{action}", response_class=HTMLResponse)
def task_pull_request(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    task: TaskDep,
    action: pull_requests.Action,
) -> Response:
    try:
        source = pull_requests.of_sync(conn, task)
        done = pull_requests.perform(conn, settings, source, action)
    except RepoCopError as exc:
        return _render_task(request, conn, settings, task, error=str(exc), status_code=400)
    if action is pull_requests.Action.OPEN:  # the new pull request, on GitHub
        return RedirectResponse(done.url, status_code=303)
    target = request.url_for("task_page", task_id=task.id)
    return RedirectResponse(target.include_query_params(pull_request=action.value), 303)


def _pull_request(conn: sqlite3.Connection, task: Task) -> pull_requests.PullRequest | None:
    return pull_requests.get(conn, task.repository_id, task.branch) if task.branch else None


def _render_task(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    task: Task,
    *,
    pull_request_done: pull_requests.Action | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    current = tasks.get(conn, task.id) or task
    offered = pull_requests.has_own(current) and current.branch is not None
    worktree = tasks.worktree(conn, settings, current) if settings.editor_url else None
    try:
        changes = tasks.worktree_changes(conn, settings, current)
    except RepoCopError:
        changes = None
    context = {
        "task": current,
        "restarted": current.error == tasks.RESTARTED,
        "repository": repositories.get(conn, current.repository_id),
        "editor_link": settings.editor_link(worktree) if worktree else None,
        "events": tasks.events_after(conn, current.id, 0),
        "changes": changes,
        "pull_request_offered": offered,
        "pull_request": _pull_request(conn, current) if offered else None,
        "pull_request_done": pull_request_done,
        "error": error,
    }
    return templates.TemplateResponse(
        request,
        "tasks/show.html",
        context | _waiting(conn, settings, current),
        status_code=status_code,
    )


def _waiting(conn: sqlite3.Connection, settings: Settings, task: Task) -> dict[str, Any]:
    """What the page says of the task when it is its repository's sync that is done but not yet
    on `origin`: where it hasn't landed, the pull request last known for its branch, and when the
    checkout last fetched. Nothing for any other task."""
    if task.workflow != template_sync.WORKFLOW or task.status is not Status.COMPLETED:
        return {}
    repository = repositories.get(conn, task.repository_id)
    waiting = template_sync.waiting(conn, settings, repository) if repository else None
    if repository is None or waiting is None or waiting.id != task.id:
        return {}
    try:
        fetched_at = repositories.last_fetch(repository, settings)
    except RepoCopError:
        fetched_at = None
    return {
        "waiting": task,
        "waiting_ref": repositories.origin_default(repository),
        "waiting_pull_request": _pull_request(conn, task),
        "fetched_at": fetched_at,
    }
