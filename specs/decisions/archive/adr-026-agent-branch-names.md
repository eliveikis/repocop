# ADR-026: Branch names say an agent made them

**Status:** accepted, its `req-<id>-<slug>` superseded by ADR-034 · **Date:** 2026-10-14

## Context

ADR-012 named a requirement's branch after its kind, `feature/req-<id>-<slug>` or `fix/req-<id>-<slug>`, and a template sync's `chore/<workflow>-<task-id>`. That follows Git Flow, which most teams have left behind for short-lived branches off `main`. The kind is already recorded with the requirement, so the prefix told nobody anything new. What a person sharing a repository with agents does need is to tell agent branches from their own, and to give them their own rules on GitHub.

## Decision

- Every branch the coordinator names starts `agent/`: `agent/req-<id>-<slug>` for a requirement, whatever its kind, and `agent/<workflow>-<task-id>` for a task without one.
- A branch named before this keeps its name. Tasks, reviews and pull requests use the branch their requirement already has.
- This supersedes ADR-012's branch names. The rest of ADR-012 stands.

## Consequences

- A repository that has a branch called `agent` can't also have `agent/…` branches. Git refuses, and the first task on a requirement fails with git's reason.
- Branches made outside the coordinator are named however their maker likes.
- A requirement's kind still shows on its page, and no longer affects its branch.

## Alternatives rejected

- **`coordinator/`.** Also true of template syncs, where no agent writes, but longer, and an agent writes almost every coordinator branch.
- **Keeping `feature/` and `fix/`.** Ritual that says nothing the requirement doesn't.
- **Renaming branches already in flight.** It would break pull requests that are open on them.
