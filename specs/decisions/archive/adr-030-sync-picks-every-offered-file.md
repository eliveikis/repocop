# ADR-030: A sync picks every file it offers, overwrites included

**Status:** accepted · **Date:** 2026-10-15

## Context

A managed template file follows the template (ADR-021), and the template's values win a merge (ADR-027). Yet a sync left a managed file that differed unpicked, so the repository kept its drifted copy and stayed behind the template unless the human remembered to tick each one.

## Decision

- The template is the authority for the files it offers. A sync picks every one by default: missing files to create, differing managed files to overwrite, and merged files to bring up to date. The human unticks a file to keep the repository's version.
- What protects the repository stays: every file is listed with its diff, the picked files are committed only on the sync's own branch, and they reach the default branch only through a pull request the human reviews and merges. A starter file the repository has is never offered.

## Consequences

- A repository that keeps a managed file different on purpose has it offered, picked, on every sync, and unticks it each time. A file every repository changes should be a starter file instead.
- Overwriting no longer needs a separate click per file, so `.claude/rules/safety.md` says what stops a silent overwrite: the visible plan, the branch and the pull request.

## Alternatives rejected

- **Keep overwrites opt-in.** It leaves drift in place by default, against the kinds that say a managed file follows the template.
