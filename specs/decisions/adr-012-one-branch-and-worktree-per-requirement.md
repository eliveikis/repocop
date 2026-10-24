# ADR-012: One branch and worktree per requirement

**Status:** accepted, its branch names superseded by ADR-026 · **Date:** 2026-09-24

## Context

A requirement is worked on by several tasks in turn (review, implement, address PR comments), and its pull request needs a single branch.

## Decision

The first task on a requirement creates its branch and worktree, and later tasks reuse them and its base commit. Branches are `feature/req-<id>-<slug>` and `fix/req-<id>-<slug>`, and `chore/<workflow>-<task-id>` for a task without a requirement.

## Consequences

- The pull request's branch is the requirement's branch.
- A requirement's tasks take turns in its worktree (ADR-017).
- A worktree that has disappeared isn't recreated.
