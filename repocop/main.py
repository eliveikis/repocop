"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from repocop import __version__, db
from repocop.config import Settings, load_settings
from repocop.routes import (
    health,
    navigation,
    pages,
    repositories,
    requirements,
    tasks,
    template_sync,
)
from repocop.routes.dependencies import check_same_origin
from repocop.services.tasks import fail_unfinished

PACKAGE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: migrate the database, and fail the tasks a stopped RepoCop left unfinished."""
    settings: Settings = app.state.settings
    with closing(db.connect(settings.database_path)) as conn:
        db.migrate(conn)
        fail_unfinished(conn)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Without settings, load them from the host config."""
    settings = settings or load_settings()
    app = FastAPI(
        title="RepoCop",
        version=__version__,
        lifespan=lifespan,
        dependencies=[Depends(check_same_origin)],
    )
    app.state.settings = settings
    app.state.templates = pages.templates(PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    app.include_router(health.router)
    app.include_router(navigation.router)
    app.include_router(repositories.router)
    app.include_router(requirements.router)
    app.include_router(tasks.router)
    app.include_router(template_sync.router)
    return app
