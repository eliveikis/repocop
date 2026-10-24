# ADR-002: SQLite through stdlib `sqlite3`, without an ORM

**Status:** accepted · **Date:** 2026-09-24

## Context

The coordinator keeps durable execution state: the repository registry, requirement references, tasks, their events and session ids. The v0.1 spec prefers SQLite for it "because it is local, simple, inspectable, and easy to migrate later", and its fixed stack rules out an ORM.

## Decision

Use stdlib `sqlite3`, with forward-only migrations numbered by `PRAGMA user_version`. No ORM.

## Consequences

- State is one local file at `database_path`, with no server to run.
- The schema and migrations are plain SQL in `coordinator/db.py`.
