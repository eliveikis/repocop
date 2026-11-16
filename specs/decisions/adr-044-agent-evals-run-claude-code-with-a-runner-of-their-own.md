# ADR-044: Agent evals run Claude Code headless, with a runner of their own

**Status:** accepted · **Date:** 2026-11-16

## Context

A change to the repo template's skills, rules or settings can make agents do the work better or worse, and nothing showed which until its failure came back, or didn't. An eval runs the same tasks several times with the template before a change and after it and compares the runs. What it measures is how an agent behaves with the template's project-level configuration: its `CLAUDE.md`, `.claude/rules/`, skills, hooks and permissions in `.claude/settings.json`.

Claude Code 2.1.282 ships an eval runner, `claude plugin eval`. By design it loads no project-level configuration, no `.claude/`, `CLAUDE.md` or rules, even ones a case's scaffold script writes: only a plugin's own skills and hooks. It compares a plugin with no plugin, not two versions of one, and most of what the template ships isn't a plugin component. The developer signs in with a Claude subscription, which Claude Code's bare mode, the documented way to run it isolated, doesn't accept. RepoCop runs no coding agent (ADR-039).

## Decision

- **A runner of the repository's own,** `evals/`, run by hand with `make eval`, as the developer runs `.reviews/review.sh`. It is development tooling, not part of RepoCop: RepoCop never runs it, and `make check` never does.
- **It runs Claude Code headless** (`claude -p`), the agent the template's skills are written for, on the developer's own sign-in, one session a run, in a throwaway repository laid out from the template at each side's ref.
- **A run is isolated by what it is told to load,** not by bare mode: project settings only, no MCP configuration but its own, no session persistence, memory and claude.ai connectors off, and an environment of only what a run needs. The eval reads what each run reports it loaded, and a run that loaded any of the developer's own configuration doesn't count.
- **Checks that give the same answer every time grade a run first,** run on the repository it leaves. `claude plugin eval`'s grader kinds (regex, tool used, tool order, file exists, model judge) are the model for what a case observes of a transcript, so cases could move to it should it come to load project configuration.

## Consequences

- The eval depends on Claude Code's headless options and its stream of events. The facts it relies on are verified against the CLI and kept in `specs/evals.md`, which a fake `claude` in `tests/fakes/` keeps in step with.
- Every run counts against the developer's subscription, so runs go one at a time and a case is kept cheap.
- Isolation is checked from what a run reports, which doesn't list `CLAUDE.md` files or memory: those were checked once against the CLI, and the eval refuses to run where a folder above a run's would hold instructions.
- Comparing two agents, or shipping the eval in the template for a managed repository, needs more than this runner offers today.

## Alternatives rejected

- **`claude plugin eval`.** It loads none of the configuration being compared, and compares with and without a plugin rather than two versions.
- **Bare mode with an API key.** It accepts only an API key, not the developer's subscription, and would bill runs apart from it.
- **A separate configuration folder and a long-lived token** (`claude setup-token` with `CLAUDE_CONFIG_DIR`), keeping runs out of `~/.claude` entirely. It is stronger isolation, but another sign-in to set up and keep; checking what each run loaded catches the same leaks.
- **The Claude Agent SDK in Python.** It would be a dependency of the repository's own tooling for what the CLI already does, and the SDK was dropped from RepoCop with ADR-039.
