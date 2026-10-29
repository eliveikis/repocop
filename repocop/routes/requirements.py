"""Requirement pages: show a requirement read-only, with the line that runs each workflow on it
in the developer's own agent. A requirement's page is found by its repository and its file name."""

from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from repocop.errors import RepoCopError
from repocop.routes.dependencies import ConnectionDep, RequirementDep, SettingsDep
from repocop.services import backlog, repositories, requirements, sessions, tasks
from repocop.services.requirements import Location

router = APIRouter()


@router.get(
    "/repositories/{repository_id}/requirements/{file_name:file}", response_class=HTMLResponse
)
def requirement_page(
    request: Request, conn: ConnectionDep, settings: SettingsDep, requirement: RequirementDep
) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    repository = repositories.get(conn, requirement.repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    error = None
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
        error = str(exc)
    shown = detail.content if detail else None
    context = {
        "repository": repository,
        "requirement": requirement,
        "detail": detail,
        "editor_link": (
            settings.editor_link(repository.primary_path / shown.path, file=True) if shown else None
        ),
        "workflow_lines": [
            tasks.workflow_line(workflow, requirement.path) for workflow in workflows
        ],
        "error": error,
        "card_name": backlog.name_of(requirement.file_name),
        "sessions": sessions.for_requirement(
            sessions.of(repository, settings), backlog.name_of(requirement.file_name)
        ),
        "change": change,
        "blocks": ordered.blocks(change) if ordered and change else (),
        "change_problems": ordered.problems_of(change) if ordered and change else (),
        "pages": ordered.pages if ordered else {},
    }
    return templates.TemplateResponse(request, "requirements/show.html", context)
