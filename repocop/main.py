"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from repocop import __version__, db
from repocop.config import Settings, load_settings
from repocop.routes import health, repositories, requirements, tasks, template_sync
from repocop.routes.dependencies import check_same_origin
from repocop.services import claude
from repocop.services.runner import TaskRunner

PACKAGE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: migrate the database, settle tasks a stopped RepoCop left, start the runner.

    Shutdown: close live Claude sessions; their tasks are settled on the next startup.
    """
    settings: Settings = app.state.settings
    with closing(db.connect(settings.database_path)) as conn:
        db.migrate(conn)
    runner = TaskRunner(settings, app.state.claude_client)
    runner.recover()
    app.state.runner = runner
    try:
        yield
    finally:
        await runner.shutdown()


def create_app(
    settings: Settings | None = None, *, claude_client: claude.ClientFactory = claude.sdk_client
) -> FastAPI:
    """Build the app. Without settings, load them from the host config."""
    settings = settings or load_settings()
    app = FastAPI(
        title="RepoCop",
        version=__version__,
        lifespan=lifespan,
        dependencies=[Depends(check_same_origin)],
    )
    app.state.settings = settings
    app.state.claude_client = claude_client
    app.state.templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    app.include_router(health.router)
    app.include_router(repositories.router)
    app.include_router(requirements.router)
    app.include_router(tasks.router)
    app.include_router(template_sync.router)
    return app
