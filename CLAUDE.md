# CLAUDE.md

**RepoCop** is a local FastAPI app, a fleet manager for agentic repositories: it keeps many unrelated Git repos in step with one repo template (the same rules, skills and spec layout), and runs coding agents' sessions against them. Each session runs in its own isolated git worktree, and many run at once.

- **Root design files:** [specs/product.md](specs/product.md) (why and for whom) and [specs/architecture.md](specs/architecture.md) (how, with Mermaid diagrams). They are the current truth: when you make or change a design decision, update them in the same change, and record a significant one in [specs/decisions/](specs/decisions/). Optional area specs (`specs/<area>.md`) are added only when a feature earns one.
- **Changes** (`specs/changes/todo/`) are requirements being delivered. Don't contradict a change; raise conflicts instead.

## Commands

```bash
make install     # uv sync: create .venv with runtime + dev deps
make check       # lint + typecheck + tests. MUST be green before you say "done"
make test        # pytest (add args: make test ARGS=... or: uv run pytest tests/x.py -k name)
make format      # ruff format + safe fixes
make run         # start RepoCop on http://127.0.0.1:8765 (same as: uv run repocop)
make doctor      # verify python / uv / git / claude CLI on this host, and the optional gh and codex
```

Always use `uv run …` (or make). Never call bare `python`, `pip`, or `pytest`.

## Stack (fixed — don't substitute)

Python 3.12+, FastAPI, Jinja2 server-rendered HTML, HTMX (vendored in `repocop/static/`), stdlib `sqlite3`, Git CLI, Claude Code (which runs the tasks), and optionally the GitHub CLI and the Codex CLI (which reviews branches), each via one wrapper module. **No** SPA framework, frontend build step, ORM, Celery/Redis, or auth in v0.1.

## Layout

```text
repocop/            app package
  main.py config.py db.py
  services/             repositories, bootstrap, template_sync, requirements, backlog, worktrees, tasks, runner, pull_requests, reviews, git, claude, github, codex
  routes/  templates/   thin handlers + Jinja
  static/               css, vendored htmx
templates/default-repo/ the repo template, synced into onboarded repos (NOT Jinja app templates)
tests/                  hermetic; fixtures in conftest.py; fakes/ (stand-ins for the Claude SDK client, the GitHub CLI and the Codex CLI)
specs/                  index.md, product.md, architecture.md, [<area>.md], decisions/, changes/{todo,archive}/
```

Don't mix up `repocop/templates/` (UI pages) with `templates/default-repo/` (files for onboarded repos).

## Invariants (details in `.claude/rules/safety.md`)

1. Agents never run in, or modify, a repo's **human-owned primary checkout**. They work only in RepoCop worktrees under `<worktrees_root>/<repo>/`: one worktree and branch per requirement (`agent/<name>`, its file name without `.md`), shared by its tasks in turn. RepoCop's only commit in the primary checkout is a UI-saved requirement file, committed alone (ADR-004).
2. Only `services/git.py` runs git, only `services/claude.py` talks to Claude Code, only `services/github.py` runs the GitHub CLI and only `services/codex.py` runs Codex, always with argv lists and never `shell=True`.
3. Never overwrite existing repo files silently, never auto-delete worktrees or branches, and never push without an explicit click or by force.
4. RepoCop's database stores execution state and references only, never copies of requirements or repo config.
5. One task ↔ one Claude session, and at most one active task per worktree. An instruction goes to exactly one session.
6. No hard-coded host paths or usernames. Everything comes from `repocop.config`.

## Working here

- The user develops on WSL2, but the code must not assume WSL (it will later run on an Ubuntu VPS).
