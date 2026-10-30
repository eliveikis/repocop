# ADR-009: A finished turn waits for the user

**Status:** superseded by ADR-039 · **Date:** 2026-09-24

## Context

A session's turn can end while the session can still be resumed, for example when Claude asks a question or stops for review. Whether the task is then finished is the user's call.

## Decision

A finished turn on a resumable session leaves the task `waiting_for_user`. It becomes `completed` only when the user marks it done, or when the workflow finishes cleanly with no follow-up needed.

## Consequences

- A waiting task is still active, so it keeps its worktree (ADR-017).
- The user continues it by sending an instruction, which resumes the session.
