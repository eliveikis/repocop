# Room for other agents

## Problem

Two things about where the product is going aren't written down, so nothing stops new work from closing them off.

**Another vendor's agent.** The coordinator runs Claude Code and nothing else. `specs/product.md` describes it as a control plane for Claude Code work, and every task depends on one vendor's product, pricing and terms. If those change for the worse, the coordinator's user has nowhere else to run the work. Most of what the coordinator knows about Claude Code is already in one module: ADR-001 put how sessions are driven behind `services/claude.py`, so that switching to the raw CLI would stay cheap. That boundary was drawn for another way of driving Claude Code, not for another agent, and nothing tells new work to keep to it. Three changes in flight build on features only Claude Code has: req-4 (its permission callback), req-5 (its sandbox) and req-6 (its trust prompt).

**More than one agent.** The product is for managing a fleet of agentic repositories: many repositories kept on the same rules, skills and spec layout, with agents working in them. `specs/product.md` doesn't say so. Its isolation pillar says one session works in a worktree at a time, which is easy to read as one agent per repository. The design has no such limit. Each requirement has its own worktree (ADR-012), and the only limit is one active task per worktree (ADR-017), so several requirements can already be in flight in one repository at once. Nothing says that is intended, so a later change could add a limit per repository, or assume one agent, without anyone noticing that it goes against the direction.

## Goal

Both are stated as the product's direction, and the rules hold new work to them: no new dependence on Claude Code outside its module, and no limit on how many agents work at once beyond one per worktree. Nothing that exists is fixed or moved by this change.

## Requirements

### 1. Agent-agnostic is a design pillar

`specs/product.md` gains a pillar: the coordinator isn't tied to one vendor's coding agent, so its user doesn't depend on one vendor's pricing and terms. It says Claude Code is the only agent supported today. The pillar's rank is open question 1.

The vision stops describing the product as Claude Code work only (open question 4 has the wording). `CLAUDE.md` and `README.md` say the same where they repeat it, and `CLAUDE.md`'s stack line says Claude Code is the agent supported today, reached through one module.

### 2. A rule against new coupling

`.claude/rules/` gains a rule: what is specific to one agent stays in that agent's module, which today is `services/claude.py`. That covers its SDK and CLI, its flags and settings files, its folder names and its prompt syntax. Other modules ask that module. A change that needs a feature only one agent has says so.

The rule lists what is outside the module today, as things to leave alone until a change calls for moving them, and not as precedent:

- where a repository's workflows are found (`.claude/skills`, in `services/tasks.py`)
- how a workflow is invoked (`/<workflow> <path>`, in `services/runner.py`)
- names the user or the database sees: `claude_bin`, `tasks.claude_session_id`, the credential panel
- the repo template, which ships `CLAUDE.md` and `.claude/`

### 3. More than one agent at once is the normal case

`specs/product.md` says what the product is for: managing a fleet of agentic repositories. It says many agents can work at once, in different repositories and on different requirements in one repository, each in its own worktree. The isolation pillar keeps its limit and says where it applies: one session per worktree at a time, not one per repository and not one per coordinator.

`.claude/rules/` gains a rule: new work adds no limit on how many agents run in a repository or across the coordinator, and doesn't assume one. Examples of assuming one: a lock held per repository, a page that shows a repository's one active task, a setting that holds a single session. A limit that is needed belongs to the worktree, or is called for by a change that says why.

### 4. Recorded as a decision

A decision record covers the pillar: the reason, what it costs, and what was rejected (staying with Claude Code by design, moving to an orchestrator that already runs several agents, building a second agent now). §3 needs no record, because it states what ADR-012 and ADR-017 already give.

## Acceptance Criteria

- `specs/product.md` has the agent-agnostic pillar at the agreed rank, with its reason, and names Claude Code as the only agent supported today.
- `specs/product.md` says the product manages a fleet of agentic repositories, that several requirements can be in flight in one repository at once, and that the one-session limit is per worktree.
- `.claude/rules/` has the rule against new coupling, with the list of what is outside `services/claude.py` today.
- `.claude/rules/` has the rule against limits per repository or per coordinator.
- `CLAUDE.md` and `README.md` agree with `specs/product.md` where they repeat it.
- A decision record covers the pillar and names the rejected alternatives.
- Apart from the test in open question 2, the change touches no code, and tasks behave as before.

## Scope boundaries

Not part of this change:

- Moving anything Claude-specific into `services/claude.py`, or renaming what is named after Claude.
- A second agent, trying one out, or choosing an agent per coordinator, repository or task.
- Changing the repo template to instructions other agents read, such as `AGENTS.md`.
- More than one worktree for a requirement, or more than one active task in a worktree (ADR-012 and ADR-017 stand).
- Agents that coordinate with each other. One agent working across several repositories stays a non-goal.
- Queues, schedules, or a cap on how many agents run at once.
- Editing req-4, req-5 or req-6 (open question 3).

## Open questions

Proposed defaults are marked **→**.

1. **The pillar's rank.** Pillars are ordered, and the higher one wins a conflict. **→** Fourth, after Isolation by construction and before Thin coordinator. It sits below the three that protect the human's work, so a safety feature only one agent has is still used, inside its module. It sits above Thin coordinator and Simple and inspectable, because keeping vendors apart costs some indirection and that cost is accepted.
2. **A test that holds the line.** **→** Yes: `tests/test_architecture.py` fails when a module other than `services/claude.py` names Claude Code's SDK, folders, flags or prompt syntax, with the places listed in §2 as its known exceptions. It is the only code in this change. The alternative is the rule alone, and prose drifts.
3. **Changes in flight that use features only Claude Code has** (req-4, req-5, req-6). **→** They stay as written, and the rule in §2 applies when each is built: what it takes from Claude Code goes in `services/claude.py`.
4. **The vision's wording.** **→** "One local control plane for a fleet of agentic repositories. A developer starts, watches and steers coding agents' work across many unrelated Git repositories, and keeps those repositories on the same rules, skills and spec layout. Every agent works in its own isolated worktree, and all durable project knowledge stays inside each repository."
5. **Whether one worktree per requirement is also only today's limit.** **→** It stays (ADR-012). This change says limits belong to the worktree. It doesn't say how many worktrees a requirement may have.
