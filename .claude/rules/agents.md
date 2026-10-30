---
paths:
  - "repocop/**"
  - "tests/**"
  - "specs/**"
---

# Agents

RepoCop runs no coding agent and isn't tied to one vendor's (`specs/product.md` › Design pillars). The developer runs the repository's workflows in their own agent tool, and many agents work at once.

## What names one agent's own

- RepoCop's code and pages name nothing specific to one agent: its SDK, CLI, flags, settings, folder and file names, permission modes or credential variables, and they build no slash command.
- `tests/test_architecture.py` fails when one does, outside the places below. Change this rule and that test together.
- These name one today. Leave them until a change calls for moving them, and don't treat them as precedent:
  - where a repository's workflows are found: `.claude/skills`, in `services/tasks.py` and the hint on a requirement's page
  - the line that runs a workflow: `/<workflow> <path>`, in `services/tasks.py`
  - where the repo template keeps the hook that records sessions, and the settings that run it: `.claude/hooks` and `.claude/settings.json`, in `services/sessions.py`
  - how a request reaches a session waiting for an instruction: Claude Code's inbox socket and its message, in `services/session_requests.py`
  - the repo template, which ships `CLAUDE.md` and `.claude/` for Claude Code, its hook that records sessions among them, `AGENTS.md` for Codex, and `.reviews/review.sh`, which runs Codex
- A change that needs a feature only one agent has says so.

## No limit on agents

- New work adds no limit on how many agents work in a repository or across RepoCop, and assumes none: no page showing a repository's one active session or branch, and no setting holding a single session.
