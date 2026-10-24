# ADR-024: The coordinator isn't tied to one coding agent

**Status:** accepted · **Date:** 2026-10-11

## Context

The coordinator runs Claude Code and nothing else, so every task depends on one vendor's product, pricing and terms. If those change for the worse, its user has nowhere else to run the work.

Most of what the coordinator knows about Claude Code is already behind `services/claude.py` (ADR-001). That boundary was drawn for another way of driving Claude Code, not for another agent, and nothing held new work to it.

## Decision

- Agent-agnostic is a design pillar, ranked fourth: below the three that protect the human's work, and above Thin coordinator and Simple and inspectable.
- Claude Code is the only agent supported today.
- What is specific to one agent stays in that agent's module, which today is `services/claude.py`. `.claude/rules/agents.md` has the rule and lists what is outside the module today, and `tests/test_architecture.py` checks it.

## Consequences

- A safety feature only one agent has is still used, inside its module, because the pillars that protect the human's work rank higher.
- Keeping vendors apart costs some indirection. That cost is accepted over the two pillars ranked below.
- Nothing is moved or renamed by this decision. What is outside the module today stays there until a change calls for moving it, and isn't precedent.
- A change that needs a feature only one agent has says so.

## Alternatives rejected

- **Staying with Claude Code by design.** The simplest, but it leaves the user with nowhere else to run the work when the vendor's product, pricing or terms change.
- **Moving to an orchestrator that already runs several agents.** It would mean giving up, or rebuilding on someone else's model, what this product exists for: the human-owned checkout, one worktree per requirement, and knowledge kept in the repository.
- **Building a second agent as part of this decision.** The direction and the boundary are needed first. A second agent is its own change, sized and decided on its own.
