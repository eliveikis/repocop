# Product — RepoCop

Root design file. It says what the product is for and who it serves. Every change should be judged against it. For *how* the system works, see [architecture.md](architecture.md).

## Vision

RepoCop is a fleet manager for agentic repositories. For a developer whose coding agents work across many unrelated Git repositories, it answers one question: is each repository in step with the repo template, and where does its work stand? The repo template gives every repository the same rules, skills and spec layout, and all durable project knowledge stays inside each repository.

RepoCop can also start, watch and steer coding agents' work. Every agent works in its own isolated worktree, and many can work at once: in different repositories, and on different requirements in one repository.

## Design pillars

These are ordered. When two pillars conflict, the higher one wins.

1. **Human keeps final control.** The human's checkout is never touched by agents. Nothing is pushed, merged, deleted, or overwritten without explicit human action, and intervening in a running session is cheap and normal.
2. **Repository owns knowledge.** Requirements, specs, CLAUDE.md, rules, and skills live in the repo. RepoCop stores references and execution history, never authoritative copies.
3. **Isolation by construction.** Each requirement gets its own worktree and branch, and one session works in it at a time. That limit is per worktree, not per repository and not for RepoCop as a whole, so several requirements can be in flight in one repository at once. Instructions reach exactly one session.
4. **Agent-agnostic.** RepoCop isn't tied to one vendor's coding agent, so its user doesn't depend on one vendor's pricing and terms. Today Claude Code runs the tasks and Codex reviews their branches, and what is specific to each stays in its own module.
5. **Thin orchestration.** RepoCop orchestrates execution and adds no reasoning of its own. Repo-specific behaviour belongs to that repo's skills and rules.
6. **Simple and inspectable.** Server-rendered HTML, SQLite, plain files, and the Git CLI. No frontend build step, no job infrastructure.

## Target audience

A single developer (or small trusted team on one host) who already uses Claude Code and works across several unrelated repositories. This audience is comfortable with Git and the terminal and wants to delegate requirement-driven work without giving up oversight.

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
| Later | Run on an always-on Linux host; authentication; richer workflow orchestration | _not yet specified_ |

## Non-goals (for now)

Multi-user auth, public deployment, distributed workers or job queues, SPA frontends, webhooks, auto-merge, a single agent working across several repos, and a plugin framework.
