# Product — RepoCop

Root design file. It says what the product is for and who it serves. Every change should be judged against it. For *how* the system works, see [architecture.md](architecture.md).

## Vision

RepoCop is a fleet manager for agentic repositories. For a developer whose coding agents work across many unrelated Git repositories, it answers one question: is each repository in step with the repo template, and where does its work stand? The repo template gives every repository the same rules, skills and spec layout, and all durable project knowledge stays inside each repository.

The developer writes requirements in their own editor and runs the repository's workflows from their own agent session, which has their search, their terminal and the context of the work so far. RepoCop shows each requirement with the line that runs each workflow on it. It does a few jobs itself, each as a task in a worktree of its own: syncing a repository with the template, reviewing a branch, opening its pull request, and running a workflow in a session it starts and the developer watches and steers. Many such tasks can work at once: in different repositories, and on different requirements in one repository.

## Design pillars

These are ordered. When two pillars conflict, the higher one wins.

1. **Human keeps final control.** The agents RepoCop starts never touch the human's checkout, and RepoCop's only write there is a fetch. Nothing is pushed, merged, deleted, or overwritten without explicit human action, and intervening in a session RepoCop runs is cheap and normal.
2. **Repository owns knowledge.** Requirements, specs, CLAUDE.md, rules, and skills live in the repo. RepoCop stores references and execution history, never authoritative copies.
3. **Isolation by construction.** Each requirement RepoCop works on gets its own worktree and branch, and one of its tasks works in it at a time. That limit is per worktree, not per repository and not for RepoCop as a whole, so several requirements can be in flight in one repository at once. Instructions reach exactly one session.
4. **Agent-agnostic.** RepoCop isn't tied to one vendor's coding agent, so its user doesn't depend on one vendor's pricing and terms. Today Claude Code runs the tasks and Codex reviews their branches, and what is specific to each stays in its own module.
5. **Thin orchestration.** RepoCop orchestrates execution and adds no reasoning of its own. Repo-specific behaviour belongs to that repo's skills and rules.
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
| Next | The fleet view: the developer's own agent does the work, and RepoCop shows where each repository and requirement stands, however the work was done | `no-requirement-editor`, `fleet-dashboard` |
| Later | Run on an always-on Linux host; authentication | _not yet specified_ |

## Non-goals (for now)

Multi-user auth, public deployment, distributed workers or job queues, SPA frontends, webhooks, auto-merge, a single agent working across several repos, a plugin framework, an editor for repository files, and extending the workflow sessions RepoCop runs itself, such as a chat interface beyond today's task page, permission prompts or sandboxing.
