---
paths:
  - "repocop/**"
  - "tests/**"
  - "specs/**"
---

# Agents

RepoCop isn't tied to one vendor's coding agent, and many agents work at once (`specs/product.md` › Design pillars). Claude Code runs the tasks' sessions; Codex reviews branches.

## One module per agent

- What's specific to one agent (its SDK and CLI, flags, settings, folder names, prompt syntax) stays in its module: `repocop/services/claude.py` for Claude Code, `repocop/services/codex.py` for Codex. Other modules ask that module, and neither agent's module names the other's.
- A change that needs a feature only one agent has says so.
- `tests/test_architecture.py` fails when another module or page template names an agent's SDK, folders, files, flags, settings, permission modes or credential variables, or builds a slash command. Change this rule and that test together.
- These are outside an agent's module today. Leave them until a change calls for moving them, and don't treat them as precedent:
  - where a repository's workflows are found: `.claude/skills`, in `services/tasks.py` and the hint on a requirement's page
  - how a workflow is invoked: `/<workflow> <path>`, in `services/runner.py`
  - names the user or the database sees: the `claude_bin` and `anthropic_api_key` settings, `tasks.claude_session_id`, the credential panel, and "Claude" in the pages' wording
  - the host check in `scripts/doctor.sh`, which knows each CLI's version, flags and sign-in command
  - the repo template, which ships `CLAUDE.md` and `.claude/` for Claude Code, and `AGENTS.md` for Codex

## No limit but one session per worktree

- New work adds no limit on how many agents run in a repository or across RepoCop, and assumes none: no lock per repository, no page showing a repository's one active task, no setting holding a single session. A limit that's needed belongs to the worktree, or to a change that says why.
