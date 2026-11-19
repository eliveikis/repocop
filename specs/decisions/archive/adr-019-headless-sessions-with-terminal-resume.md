# ADR-019: Headless sessions, continued in a terminal with `--resume`

**Status:** superseded by ADR-039 · **Date:** 2026-09-28

## Context

A user sometimes wants to take over a session by hand in a terminal.

## Decision

Sessions stay headless SDK sessions. Once no task is active in its worktree, a task's page shows the command that continues its session: `cd <worktree> && claude --resume <session id>`.

## Consequences

- The command is hidden while any task in the worktree is active, because the coordinator may still resume or start a session there, and two writers in one session interleave.
- The coordinator doesn't track what happens in that terminal.

## Alternatives rejected

- **Claude Code's background sessions** (`claude --bg`, `claude attach`, agent view; a research preview in 2.1.282): nothing can send a message to one without attaching, their supervisor restarts sessions and stops idle ones on its own, which clashes with restart recovery (ADR-010), and their state can only be polled.
