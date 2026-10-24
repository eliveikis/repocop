# ADR-017: One active task per worktree

**Status:** accepted · **Date:** 2026-09-25

## Context

A requirement's tasks share one worktree (ADR-012), and two sessions writing in one worktree would interleave (invariant 5).

## Decision

- `queued`, `running` and `waiting_for_user` are active, and at most one task per worktree is active, enforced by the database.
- A queued task can be cancelled.
- A task's workflow is a skill committed at HEAD.
- Later tasks reuse the requirement's worktree, branch and base commit. A missing worktree isn't recreated.

## Consequences

- The next task on a requirement waits until the current one is marked done or cancelled.
