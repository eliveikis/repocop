# ADR-013: Requirement identity

**Status:** accepted, its heading superseded by ADR-031 and its id by ADR-034 · **Date:** 2026-09-24

## Context

Requirements are Markdown files in each repository, named the same way in files, branches and the UI across unrelated repositories. The database may be lost, but the files survive.

## Decision

- Every requirement has a global id from the coordinator's counter.
- Its file is `req-<id>-<slug>.md` and starts with `# <name>`. The slug comes from the name and is fixed at creation.
- Its kind (feature or fix) is coordinator metadata, not part of the file.

## Consequences

- The file carries no metadata beyond its heading.
- Renaming a requirement changes only its heading, because its branch may already exist.
- To survive a lost database, the next id also counts ids found on disk.
