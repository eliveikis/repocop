# ADR-010: Restart recovery stops leftovers and restarts nothing

**Status:** superseded by ADR-039, but for failing a task left unfinished at startup · **Date:** 2026-09-24

## Context

A hard-killed coordinator can leave its Claude Code process working. Checked against the real CLI: it finished its turn unattended, about 20 s of file writes, then exited.

## Decision

- While a session runs, its process is recorded (id and start time), and cleared when it ends.
- On startup, the runner stops the process each `running` or `queued` task recorded, if that exact process still runs, and notes where the task stopped.
- A `running` task with a session id becomes `waiting_for_user`. Any other becomes `failed` (`coordinator_restarted`).
- Nothing restarts on its own. A failed or cancelled task can be started again.

## Consequences

- The human decides what happens next, with the note on the task page.
- Process lookup uses `/proc` (Linux), so elsewhere nothing is recorded.
