# ADR-016: Requirement storage

**Status:** accepted, its next id superseded by ADR-034 and its saves by ADR-037 · **Date:** 2026-09-25

## Context

The coordinator reads and writes requirement files in human-owned checkouts, where the human may edit the same files at the same time. The database stores references only (invariant 4).

## Decision

- One folder per repository: the requirement path pattern's placeholders sit only in the file name.
- The next id comes from the database and from disk.
- Each save is a commit of that file alone.
- An edit is refused if the file changed since it was read.
- Whether a requirement is archived or missing is read from disk.

## Consequences

- Edits are never lost, and archiving is a move into the `archive/` folder beside the requirements folder.
