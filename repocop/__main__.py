"""Entry point: `make run`, `uv run repocop`, or `python -m repocop`."""

import logging

import uvicorn

from repocop.config import load_settings
from repocop.errors import ConfigError
from repocop.main import create_app

logger = logging.getLogger("repocop")

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(2) from exc
    if settings.host not in LOOPBACK_HOSTS:
        logger.warning(
            "Binding to %s. v0.1 has no authentication: anyone who can reach this address "
            "controls RepoCop.",
            settings.host,
        )
    logger.info("Primary checkouts (human-owned): %s", settings.repos_root)
    logger.info("Agent worktrees (RepoCop-owned): %s", settings.worktrees_root)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
