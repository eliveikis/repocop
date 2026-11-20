# ADR-028: Archived changes are named by when they were archived

**Status:** accepted · **Date:** 2026-10-14

## Context

`/complete-change` moved a delivered change into `archive/` under the name it had, on the grounds that its `req-<id>-` prefix was its identity and git records when it moved. In practice the archive listed changes alphabetically, a change archived without an id had no order at all, and the time it was archived was only visible to someone running `git log`.

## Decision

- An archived change's name is its old name stamped with the UTC date and time it was archived: `2026-10-14T150616Z-req-12-bulk-import.md`. The stamp sorts in order, `T` and `Z` mark it as UTC, and it has no colons, which Windows file names don't allow.
- The skill makes the move with one script beside it, `archive.sh`, which stamps the name, `git mv`s the file and lists what still mentions its old path.
- The coordinator finds an archived requirement by its name after an optional stamp, and reads ids past it, so an archive made before this keeps working. Of several, the latest stamp wins.

## Consequences

- The archive lists changes in the order they finished, and every archived change has a unique, dated name.
- A link to an archived change changes when it is archived. Specs, rules and skills never link to archived changes, so only other documents need it.
- This repository's existing archive was renamed by the time git recorded for each move. Other repositories keep their older names until they rename them.
