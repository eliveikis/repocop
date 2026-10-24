# ADR-021: Template files have a kind

**Status:** accepted, its merge rule superseded by ADR-027 · **Date:** 2026-09-29

## Context

Some template files should follow the template. Others, such as `CLAUDE.md` and the spec stubs, are filled in by each repository and must never be offered for overwrite. Settings are JSON that a repository extends with its own entries.

## Decision

Each file's kind is declared in the template's `template.toml`, which is never copied:

- **managed** (the default): sync offers to overwrite it when it differs.
- **starter:** created when missing, then the repository's own, and never offered.
- **merged:** JSON that sync only adds the template's missing entries to.

The shared, always-loaded `principles.md` rule, not `CLAUDE.md`, points sessions at `specs/`.

## Consequences

- Because `CLAUDE.md` is a starter file, anything every repository needs from the template goes in a managed file.
