# ADR-018: Sessions use the Claude Code subscription by default

**Status:** accepted · **Date:** 2026-09-26

## Context

Running workflows should draw on the host's Claude Code subscription (e.g. a Max plan) rather than a separately billed API key (v0.1 spec). An inherited key or token could silently switch that.

## Decision

- Sessions use the host's Claude Code subscription login by default. `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are blanked in each session's environment, then a configured key is set.
- An API key is an explicit option.
- A session reporting a different credential than configured is stopped with the reason.
- The main page shows which credential is in use.

## Consequences

- Neither an inherited key nor an inherited token can take over. The real CLI lets a token win even over a key, so both are blanked.
