# ADR-015: Onboarding by remote identity

**Status:** accepted · **Date:** 2026-09-25

## Context

A repository is added by its remote URL, or by name for a checkout already on disk. Checkouts that already exist are human-owned, and the same remote can be spelled many ways.

## Decision

- Paths come from the repository's name: `<repos_root>/<name>` and `<worktrees_root>/<name>/`.
- Remotes are deduplicated by identity (host and path), whatever their spelling.
- An existing checkout is registered only when its `origin` has the same identity, and is never changed. It can be added by name alone, using its `origin`.
- Otherwise the coordinator clones, inside the add request, with a timeout.

## Consequences

- Cloning inside the request is simple, but holds a request for up to 10 minutes. Revisit once the task manager exists.
