"""Repository pages: the main page with the fleet's active work and each repository's standing,
adding a repository and choosing its default branch, fetching one repository or all of them, each
repository's page with its board, changing its default branch, and removing a completed template
sync's branch."""

import contextlib
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from repocop.config import Settings
from repocop.errors import RepoCopError
from repocop.routes.dependencies import ConnectionDep, RepositoryDep, SettingsDep
from repocop.services import (
    board,
    pull_requests,
    repositories,
    requirements,
    sessions,
    tasks,
    template_sync,
)
from repocop.services.board import Stage
from repocop.services.repositories import Outcome, Registration, Repository, Status
from repocop.services.tasks import Task

CHANGED_FILES_SHOWN = 100  # a checkout's changed files listed on its page; the rest are counted
ACTIVE = (Stage.IN_PROGRESS, Stage.IN_REVIEW)  # the stages the main page shows across the fleet

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def list_repositories(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    registered: int | None = None,
    outcome: Outcome | None = None,
    pull_requests: bool = False,
) -> HTMLResponse:
    """The main page: the requirements in progress or in review in any repository, and each
    repository's standing. It shows at once, and pull requests are read after it, unless
    `pull_requests` asks for them now, as a browser without JavaScript does."""
    registration = None
    if registered is not None and outcome is not None:
        repository = repositories.get(conn, registered)
        registration = Registration(repository, outcome) if repository else None
    return _render_list(
        request, conn, settings, registration=registration, with_pull_requests=pull_requests
    )


@router.get("/board", response_class=HTMLResponse)
def board_panel(
    request: Request, conn: ConnectionDep, settings: SettingsDep, repository: int | None = None
) -> HTMLResponse:
    """A board with open pull requests read from GitHub now: the repository's own, or else the
    fleet's active work, with each repository's counts to swap into the main page."""
    if repository is None:
        listed = repositories.list_all(conn)
        context = _fleet_board(listed, board.read(settings, listed, with_pull_requests=True))
        context["counts_oob"] = True
    else:
        found = repositories.get(conn, repository)
        if found is None:
            raise HTTPException(status_code=404, detail="repository not found")
        context = _own_board(found, board.read(settings, [found], with_pull_requests=True))
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "partials/board.html", context)


@router.get("/repositories/new", response_class=HTMLResponse)
def new_repository(request: Request, settings: SettingsDep) -> HTMLResponse:
    """The form that adds a repository by its remote URL or the name of its checkout."""
    return _render_new(request, settings)


@router.post("/repositories", response_class=HTMLResponse)
def add_repository(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    remote_url: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    default_branch: Annotated[str, Form()] = "",
) -> Response:
    """Add a repository in two steps. Without `default_branch`, show what adding it does and ask
    for its default branch, suggesting the one `origin` names. With it, register it."""
    try:
        if default_branch.strip():
            registration = repositories.register(
                conn, settings, remote_url, name, default_branch=default_branch
            )
        else:
            proposed = repositories.propose(conn, settings, remote_url, name)
            if isinstance(proposed, repositories.Candidate):
                templates: Jinja2Templates = request.app.state.templates
                context = {"candidate": proposed}
                return templates.TemplateResponse(request, "repositories/add.html", context)
            registration = proposed
    except RepoCopError as exc:
        form = {"remote_url": remote_url, "name": name}
        return _render_new(request, settings, error=str(exc), form=form, status_code=400)
    target = request.url_for("list_repositories").include_query_params(
        registered=registration.repository.id, outcome=registration.outcome.value
    )
    return RedirectResponse(target, status_code=303)


@router.post("/repositories/fetch-all", response_class=HTMLResponse)
def fetch_all_repositories(
    request: Request, conn: ConnectionDep, settings: SettingsDep
) -> HTMLResponse:
    """Fetch every repository whose checkout is there, each as its own Fetch does."""
    listed = [r for r in repositories.list_all(conn) if repositories.checkout_present(r, settings)]
    fetched = repositories.fetch_each(listed, settings)
    summary = {
        "fetched": sum(1 for repository in listed if fetched[repository.id].error is None),
        "of": len(listed),
        "failures": [(r, fetched[r.id].error) for r in listed if fetched[r.id].error],
        "offers": [
            (r, offered)
            for r in listed
            if (offered := fetched[r.id].origin_default) and offered != r.default_branch
        ],
    }
    return _render_list(request, conn, settings, fetched_all=summary)


@router.get("/repositories/{repository_id}", response_class=HTMLResponse)
def repository_page(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    repository: RepositoryDep,
    fetched: bool = False,
    removed: str | None = None,
    origin_default: str | None = None,
    default_branch_set: bool = False,
    pull_requests: bool = False,
) -> HTMLResponse:
    """A repository's page. Its board shows at once, and its pull requests are read after it,
    unless `pull_requests` asks for them now, as a browser without JavaScript does."""
    return _render_repository(
        request,
        conn,
        settings,
        repository,
        fetched=fetched,
        removed=removed,
        origin_default=origin_default,
        default_branch_set=default_branch_set,
        with_pull_requests=pull_requests,
    )


@router.post("/repositories/{repository_id}/fetch", response_class=HTMLResponse)
def fetch_repository(
    request: Request, conn: ConnectionDep, settings: SettingsDep, repository: RepositoryDep
) -> Response:
    try:
        origin_default = repositories.fetch(repository, settings)
    except RepoCopError as exc:
        return _render_repository(
            request, conn, settings, repository, fetch_error=str(exc), status_code=400
        )
    params = {"fetched": "true"}
    if origin_default and origin_default != repository.default_branch:
        params["origin_default"] = origin_default  # offered on the page, never switched to
    target = request.url_for("repository_page", repository_id=repository.id)
    return RedirectResponse(target.include_query_params(**params), status_code=303)


@router.post("/repositories/{repository_id}/default-branch", response_class=HTMLResponse)
def change_default_branch(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    repository: RepositoryDep,
    default_branch: Annotated[str, Form()] = "",
) -> Response:
    try:
        repositories.set_default_branch(conn, settings, repository, default_branch.strip())
    except RepoCopError as exc:
        return _render_repository(
            request, conn, settings, repository, default_branch_error=str(exc), status_code=400
        )
    target = request.url_for("repository_page", repository_id=repository.id)
    return RedirectResponse(target.include_query_params(default_branch_set="true"), 303)


@router.post("/repositories/{repository_id}/syncs/{task_id}/remove", response_class=HTMLResponse)
def remove_sync(
    request: Request,
    conn: ConnectionDep,
    settings: SettingsDep,
    repository: RepositoryDep,
    task_id: int,
) -> Response:
    task = tasks.get(conn, task_id)
    if task is None or task.repository_id != repository.id:
        raise HTTPException(status_code=404)
    try:
        template_sync.remove(conn, settings, task)
    except RepoCopError as exc:
        return _render_repository(
            request, conn, settings, repository, sync_error=str(exc), status_code=400
        )
    target = request.url_for("repository_page", repository_id=repository.id)
    return RedirectResponse(target.include_query_params(removed=task.branch), status_code=303)


def _render_repository(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    repository: Repository,
    error: str | None = None,
    status_code: int = 200,
    *,
    fetched: bool = False,
    fetch_error: str | None = None,
    removed: str | None = None,
    sync_error: str | None = None,
    origin_default: str | None = None,
    default_branch_set: bool = False,
    default_branch_error: str | None = None,
    with_pull_requests: bool = False,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    status = repositories.status(repository, settings)
    waiting = _waiting(conn, settings, repository, status)
    origin_branches = None
    if status is not Status.MISSING:
        with contextlib.suppress(RepoCopError):  # without them, the default branch can't change
            origin_branches = repositories.origin_branches(repository, settings)
    context = {
        "repository": repository,
        "status": status,
        "waiting": waiting,
        "waiting_ref": repositories.origin_default(repository),
        "waiting_pull_request": (
            pull_requests.get(conn, repository.id, waiting.branch)
            if waiting and waiting.branch
            else None
        ),
        "checkout": _checkout(repository, settings, status),
        "remote": repositories.remote(repository, settings),
        "origin_branches": origin_branches,
        "origin_default": (
            origin_default
            if origin_branches
            and origin_default in origin_branches.branches
            and origin_default != repository.default_branch
            else None
        ),
        "default_branch_set": default_branch_set,
        "default_branch_error": default_branch_error,
        "changed_shown": CHANGED_FILES_SHOWN,
        "fetched": fetched,
        "fetch_error": fetch_error,
        **_own_board(
            repository, board.read(settings, [repository], with_pull_requests=with_pull_requests)
        ),
        "sessions": sessions.of(repository, settings),
        "recorded": (
            sessions.recorder_on_origin(repository, settings)
            if status is not Status.MISSING
            else None
        ),
        "todo_dir": requirements.todo_dir(repository),
        "syncs": tasks.list_for_repository(conn, repository, workflow=template_sync.WORKFLOW),
        "sync_states": template_sync.states(conn, settings, repository),
        "removed": removed,
        "sync_error": sync_error,
        "error": error,
    }
    return templates.TemplateResponse(
        request, "repositories/show.html", context, status_code=status_code
    )


def _waiting(
    conn: sqlite3.Connection, settings: Settings, repository: Repository, status: Status
) -> Task | None:
    """The sync waiting to reach `origin`, for a repository behind the template."""
    return template_sync.waiting(conn, settings, repository) if status is Status.BEHIND else None


def _checkout(repository: Repository, settings: Settings, status: Status) -> dict[str, Any]:
    """What a page shows of a primary checkout: its git state, or why that can't be read, and
    the link that opens it in the editor. Empty when the checkout is missing."""
    if status is Status.MISSING:
        return {}
    shown: dict[str, Any] = {"editor_link": settings.editor_link(repository.primary_path)}
    try:
        shown["state"] = repositories.checkout_state(repository, settings)
    except RepoCopError as exc:
        shown["error"] = str(exc)
    return shown


def _own_board(repository: Repository, read: board.Board) -> dict[str, Any]:
    """What a repository's page shows of its board: every stage, as only its own."""
    return {"board": read, "stages": tuple(Stage), "scope": repository}


def _fleet_board(listed: list[Repository], read: board.Board) -> dict[str, Any]:
    """What the main page shows of the fleet's board: the active stages of every repository, and
    each repository's sessions on none of their requirements."""
    return {
        "board": read,
        "stages": ACTIVE,
        "scope": None,
        "apart": read.apart_from(ACTIVE),
        "registered": listed,
    }


def _render_new(
    request: Request,
    settings: Settings,
    *,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    context = {
        "settings": settings,
        "error": error,
        "form": form or {"remote_url": "", "name": ""},
    }
    return templates.TemplateResponse(
        request, "repositories/new.html", context, status_code=status_code
    )


def _render_list(
    request: Request,
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    registration: Registration | None = None,
    with_pull_requests: bool = False,
    fetched_all: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    listed = []
    offered: dict[int, int] = {}
    for repo in repositories.list_all(conn):
        status = repositories.status(repo, settings)
        waiting = _waiting(conn, settings, repo, status)
        checkout = _checkout(repo, settings, status)
        listed.append((repo, status, waiting, checkout, repositories.remote(repo, settings)))
        if status is Status.BEHIND and waiting is None:
            with contextlib.suppress(RepoCopError):  # a plan that can't be read offers nothing
                offered[repo.id] = len(repositories.template_plan(repo, settings).offered)
    registered = [repo for repo, *_ in listed]
    read = board.read(settings, registered, with_pull_requests=with_pull_requests)
    context = {
        "settings": settings,
        "repositories": listed,
        "offered": offered,
        **_fleet_board(registered, read),
        "fetched_all": fetched_all,
        "registration": registration,
    }
    return templates.TemplateResponse(
        request, "repositories/list.html", context, status_code=status_code
    )
