---
paths:
  - "repocop/**/*.py"
  - "tests/**/*.py"
---

# Python conventions

- Python 3.12+ syntax: `X | None`, `list[str]`, `match`, and `pathlib.Path` throughout (ruff `PTH` enforces it).
- Full type hints, passing `mypy --strict`. At module boundaries, `dataclass(frozen=True)` or Pydantic models, not loose dicts.
- Configuration comes **only** from `repocop.config`: no `os.environ` reads elsewhere (process wrappers may pass the environment to child processes), and no hard-coded home dirs, usernames or `/mnt/c` paths.
- Persistence is stdlib `sqlite3` behind `repocop/db.py`: parameterized queries, explicit transactions, no ORM in v0.1, and schema changes as new forward-only migrations.
- Timestamps are UTC ISO-8601 strings from `datetime.now(UTC)`.
- Services are plain functions or small classes taking their dependencies (config, db connection) as arguments, so they test without FastAPI.
- Route handlers stay thin: parse the form, call a service, render a template. No git or subprocess calls in routes.
- Dependencies point one way: `main.py` → `routes/` → `services/` → `db.py`, `config.py`, `errors.py`. Nothing imports a layer above it, only `main.py` and `routes/` know FastAPI, and imports are absolute.
- `tests/test_architecture.py` enforces the layer direction, environment access and which modules launch processes. Change a rule here and in that test together.
- Surface errors to the UI: raise a `RepoCopError` subclass and render it. Never `except Exception: pass`.
- Log with `logging.getLogger(__name__)`, never `print`.
- A new runtime dependency needs a reason, and nothing the stack in `CLAUDE.md` rules out (Celery, Redis, SPA frameworks, …) gets added.
