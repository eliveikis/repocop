# ADR-014: Immutable settings with an explicit loader

**Status:** accepted · **Date:** 2026-09-24

## Context

Every part of the coordinator needs configuration, and nothing may hard-code host paths or usernames (invariant 6).

## Decision

`coordinator/config.py` is the only module that reads config files or the environment. It is an immutable pydantic `Settings` model plus a small explicit loader, without `pydantic-settings`: a fixed file search order, `COORDINATOR_<KEY>` overrides, and strict validation.

## Consequences

- A mistyped key, or an invalid value, fails at load with a readable message.
- Everything else receives settings, never reads them.
