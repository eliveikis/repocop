# ADR-003: Every coordinator session runs in a worktree

**Status:** superseded by ADR-039 · **Date:** 2026-09-24

## Context

Agents must never run in, or modify, a repository's human-owned primary checkout (invariant 1). Some workflows, such as `review-requirement`, only read, so they could in principle run there.

## Decision

Every coordinator-launched session runs in a coordinator worktree, including `review-requirement`. There are no exceptions.

## Consequences

- `services/claude.py` refuses any other working directory, and that one check covers every workflow.
- A read-only workflow still gets a worktree.
