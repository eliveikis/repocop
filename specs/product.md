# Product — RepoCop

Root design file. It says what the product is for and who it serves. Every change should be judged against it. For *how* the system works, see [architecture.md](architecture.md).

## Vision

RepoCop is a fleet manager for agentic repositories. For a developer whose coding agents work across many unrelated Git repositories, it answers one question: is each repository in step with the repo template, and where does its work stand? The repo template gives every repository the same rules, skills and spec layout, and all durable project knowledge stays inside each repository.

The developer writes requirements in their own editor and runs the repository's workflows in their own agent tool, such as Claude Code's agent view, a terminal or VS Code, where the agent has their sign-in, their permissions and the context of the work so far. RepoCop runs no coding agent. It shows each requirement with the line that runs each workflow on it and the branch to do it on, and its board shows where every requirement stands, however and by whomever the work was done. Each session reports what it does as it does it, so RepoCop also shows what is being worked on right now, and which session waits for the developer, wherever it was started. From a requirement's page, the developer asks one of its live sessions to run the next workflow on it, which the session takes when its turn ends, or at once if it waits for an instruction. Its one job of its own is keeping each repository in step with the template: a sync, committed on a branch in a worktree of its own, which reaches the repository only through a pull request the developer merges. Many agents work at once: in different repositories, and on different requirements in one repository.

## Design pillars

These are ordered. When two pillars conflict, the higher one wins.

1. **Human keeps final control.** RepoCop's only write in the human's checkout is a fetch. Nothing is pushed, merged, deleted, or overwritten without explicit human action, and the developer runs and steers every agent in their own session.
2. **Repository owns knowledge.** Requirements, specs, CLAUDE.md, rules, and skills live in the repo. RepoCop stores references and the record of its own syncs, never authoritative copies.
3. **Isolation by construction.** What RepoCop writes, a template sync, it writes on a branch in a worktree of its own, never in the human's checkout. It sets no limit on how many agents work at once, in a repository or across the fleet, and assumes none.
4. **Agent-agnostic.** RepoCop runs no coding agent and isn't tied to one vendor's, so its user doesn't depend on one vendor's pricing and terms. The repo template ships rules and skills for Claude Code and Codex, and what in RepoCop is specific to one agent is kept to a few known places.
5. **Thin orchestration.** RepoCop shows where work stands and keeps repositories in step, and adds no reasoning of its own. Repo-specific behaviour belongs to that repo's skills and rules, run by the developer's own agent.
6. **Simple and inspectable.** Server-rendered HTML, SQLite, plain files, and the Git CLI. No frontend build step, no job infrastructure.

## Target audience

A single developer (or small trusted team on one host) who works across several unrelated repositories with a coding agent such as Claude Code, writing requirements in their own editor and running the agent in their own session. This audience is comfortable with Git and the terminal, and wants every repository on the same rules, skills and spec layout, and to see where each one's work stands without giving up oversight.

v0.1 is **single-user and local**, with no authentication.

## Platform targets

| Stage | Host | Access |
|-------|------|--------|
| Now | WSL2 on a developer workstation | Browser on `127.0.0.1` |
| Later | Always-on Linux host (e.g. Ubuntu VPS) | Behind a reverse proxy, with auth added |

Nothing may assume WSL. Host-specific paths come from configuration.

## Monetization

None planned. Running and steering agents is a crowded field of free tools, and the buyers who pay need authentication, several users and hosting, all non-goals. RepoCop is free software instead, which pays in reputation, feedback and adoption: the app is licensed MIT, and the repo template MIT No Attribution, so the files it copies into other repositories carry no obligation.

## Roadmap

High-level themes. Each is delivered through one or more changes under `changes/`.

| Release | Theme | Change |
|-----------|-------|--------|
| v0.1 | RepoCop proven end-to-end on one machine: onboard → requirement → review → implement in a worktree → observe and steer → inspect diff | delivered |
| Next | The fleet view: the developer's own agent does the work, and RepoCop shows where each repository and requirement stands, however the work was done | `no-requirement-editor`, `fleet-dashboard`, `no-agent-runs`, `session-events`, `queue-next-step` |
| Later | Run on an always-on Linux host; authentication | _not yet specified_ |

## Non-goals (for now)

Multi-user auth, public deployment, distributed workers or job queues, SPA frontends, webhooks, auto-merge, a single agent working across several repos, a plugin framework, an editor for repository files, and running or hosting coding agents itself: the developer's own agent tool does that.
