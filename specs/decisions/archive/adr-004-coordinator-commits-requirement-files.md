# ADR-004: The coordinator commits the requirement files it saves

**Status:** superseded by ADR-037 · **Date:** 2026-09-24

## Context

A task's worktree is cut from the primary checkout's HEAD, so a requirement reaches a worktree only once it's committed. The primary checkout belongs to the human, who may have other work staged there.

## Decision

- Saving a requirement in the UI commits that file only (`git commit -- <path>`) on the branch that's checked out, and is refused mid-merge, mid-rebase or on a detached HEAD.
- Worktrees start from the primary checkout's HEAD.
- An uncommitted requirement blocks task start with a notification that offers the same single-file commit.

## Consequences

- This is the coordinator's only commit in a primary checkout.
- Nothing is copied into a worktree behind the human's back.
- Edits made after a task starts reach it only through an instruction.
