# ADR-039: RepoCop runs no coding agents

**Status:** accepted · **Date:** 2026-10-29

## Context

RepoCop started Claude Code sessions in worktrees of its own, one per requirement, and steered them from its task pages (ADR-001, ADR-003, ADR-012). It ran Codex's review of those branches (ADR-025) and opened their pull requests (ADR-023). The developer stopped using that path: they run the workflows in their own agent tool, such as Claude Code's agent view, a terminal or VS Code, where the agent has their sign-in, their permissions and the conversation so far, and where many sessions run side by side. The board already reads every requirement's stage from its repository and GitHub, however the work was done (ADR-038).

The unused path was most of RepoCop's code: a background runner, a vendor SDK, restart recovery of live processes, sign-in checks, permissions, a transcript and instruction box, and a database record of the requirements it ran. It tied RepoCop to one vendor's SDK, and it gave a requirement two ways of being worked on that the board, and the session events to come, would have to tell apart.

## Decision

- **RepoCop launches no coding agent:** no Claude Code session and no Codex review. Only `services/git.py` and `services/github.py` launch processes, and nothing imports an agent's SDK, which `tests/test_architecture.py` checks.
- **It shows, and gives the line.** A requirement's page gives the line that runs each of the repository's workflows on it in the developer's own agent, with a Copy button, and names the branch to do the work on. It offers no start, review or pull request action.
- **Its one job of its own is template sync**, which stays a task with its worktree, branch, page and pull request actions. At startup, a sync a stopped RepoCop left queued or running fails as `app_restarted`, so it can be run again.
- **What only agent runs used goes.** A forward-only migration deletes past workflow runs and reviews with their events, the record of the requirements they ran on, the sessions' columns, and the pull request addresses of requirement branches. Their worktrees and branches stay on disk, untouched, as RepoCop never deletes them. The settings only they used (`claude_bin`, `anthropic_api_key`, `review_model`, `review_effort`) are refused by name.
- **Reviews are the repository's.** The template's `.reviews/review.sh` runs Codex's review by hand and owns its read-only options.

This supersedes ADR-001, ADR-003, ADR-008, ADR-009, ADR-017, ADR-018, ADR-019 and ADR-025; ADR-010, but for failing a task left unfinished at startup; ADR-012; ADR-023 for requirement branches; and ADR-034's database row for a requirement. ADR-024's pillar stands, with no agent's module left to keep each one's specifics in: `.claude/rules/agents.md` lists the few places that name them. ADR-026's `agent/` prefix stays, for sync branches.

## Consequences

- RepoCop no longer depends on a vendor SDK, and needs neither Claude Code nor Codex on its host. `make doctor` checks only what RepoCop runs.
- Nothing in RepoCop is running when no request is: there is no background work to recover but a sync cut off mid-request.
- The developer sees a session's progress in their own agent tool, not in RepoCop.
- Reviewing a branch and opening its pull request are done in the repository, by hand or by its own skills, run in the agent's session, where the work is in view.
- Past run history is gone after the upgrade. Its branches and worktrees stay, and the board still reads their branches.

## Alternatives rejected

- **Keep the runner, unused.** It keeps most of the code, a vendor SDK and two ways of working on a requirement for no user.
- **Keep the history of past runs read-only.** The pages and records it needs outlive what they describe, and nothing would act on them.
- **Run the developer's own agent tool from RepoCop.** It is what was dropped: the developer's tool already runs, shows and steers sessions, with their sign-in and permissions.
