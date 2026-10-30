"""Request-scoped dependencies: settings, a database connection, lookups of what a path names,
the `file` path segment that names a file, and the check that a request which changes state comes
from RepoCop's own pages."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import Depends, HTTPException, Request
from starlette.convertors import Convertor, register_url_convertor

from repocop import db
from repocop.config import Settings
from repocop.services import repositories, requirements, tasks
from repocop.services.repositories import Repository
from repocop.services.requirements import Requirement
from repocop.services.tasks import Task

READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class FileConvertor(Convertor[str]):
    """A path segment holding a file name, as `{name:file}`. A URL built for one is
    percent-encoded, so a name with `#`, `?`, `%` or a space still leads to its own page."""

    regex = "[^/]+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return quote(value, safe="")


register_url_convertor("file", FileConvertor())


def check_same_origin(request: Request) -> None:
    """Refuse a request that changes state when a page on another site made the browser send it.

    A browser says where a request comes from: in `Sec-Fetch-Site`, or else in `Origin`, which
    must name the host the request was sent to. A request with neither isn't from a browser.
    """
    if request.method in READ_ONLY_METHODS:
        return
    site, origin = request.headers.get("sec-fetch-site"), request.headers.get("origin")
    if site is not None:
        own = site in ("same-origin", "none")
    elif origin is not None:
        own = urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower()
    else:
        own = True
    if not own:
        raise HTTPException(
            status_code=403,
            detail="this request came from another site, so RepoCop refused it",
        )


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_connection(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[sqlite3.Connection]:
    """A connection for one request, closed when the request ends."""
    conn = db.connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnectionDep = Annotated[sqlite3.Connection, Depends(get_connection)]


def get_repository(repository_id: int, conn: ConnectionDep) -> Repository:
    """The repository named in the path, or 404."""
    repository = repositories.get(conn, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return repository


def get_task(task_id: int, conn: ConnectionDep) -> Task:
    """The task named in the path, or 404."""
    task = tasks.get(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


RepositoryDep = Annotated[Repository, Depends(get_repository)]
TaskDep = Annotated[Task, Depends(get_task)]


def get_requirement(
    repository: RepositoryDep, file_name: str, settings: SettingsDep
) -> Requirement:
    """The requirement whose file the path names in the repository, or 404."""
    requirement = requirements.find(settings, repository, file_name)
    if requirement is None:
        raise HTTPException(status_code=404, detail="requirement not found")
    return requirement


RequirementDep = Annotated[Requirement, Depends(get_requirement)]
