# ADR-006: Template sync, chosen per file and applied on a worktree branch

**Status:** accepted · **Date:** 2026-09-24

## Context

The repo template changes after repositories are onboarded from it. A repository's primary checkout is human-owned, and existing files are never overwritten silently (invariant 3).

## Decision

Onboarding and sync share one planner. The user picks, per file, what to create, overwrite, merge or keep. Sync applies the picked files on its own worktree branch, never in the primary checkout.

## Consequences

- The human reviews and merges a sync like any agent's work, and controls what a template update overwrites.
- There's no template version tracking and no three-way merge: a differing file is kept or overwritten whole.
