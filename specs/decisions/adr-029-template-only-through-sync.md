# ADR-029: The repo template reaches a repository only through sync

**Status:** accepted · **Date:** 2026-10-14

## Context

There were two ways to bring the repo template into a repository. Set up wrote the template's missing files into the human-owned primary checkout and left them uncommitted (ADR-011). Sync committed the files the user picked on a worktree branch, for a pull request (ADR-006). They judged a repository differently: Set up by the files on disk, Sync by the default branch as committed. So a repository could need setting up after its files were synced, or count as set up while they sat uncommitted, and the same files were offered twice.

## Decision

- Sync is the only way the template's files reach a repository, a new one's first files included. The coordinator writes no template files into a primary checkout.
- A repository's status says whether its default branch is behind the template, from the same comparison a sync plans with, and links to Sync. A repository with no commits says it needs a first commit, since a sync branch starts from one.
- The comparison is with the default branch on `origin`, as last fetched, and a sync branch starts from the same commit. A merged sync lands there, and the coordinator never pulls into the human's checkout, so comparing with the checkout's own branch would offer a merged sync's files again until the human pulled.
- The comparison reads the branch with one git call, so it can run on every page load.

## Consequences

- A new repository gets the template as a pull request the human reviews, like any template update. Without a GitHub remote, the human merges the sync branch themselves.
- Nothing fetches on its own, so after a sync is merged the status shows it once the human clicks Fetch. Commits on the checkout's own default branch that aren't pushed don't count.
- The only coordinator writes in a primary checkout are a saved requirement file and a fetch.
- A repository that keeps a managed file different on purpose shows as behind the template until one of them changes.
- The template's empty folders, kept there by `.gitkeep`, are no longer created in a checkout. Git couldn't commit them anyway.

## Alternatives rejected

- **Keep Set up, but judge it by the default branch.** There would still be two ways to apply the same files, one of them writing into a checkout the human owns.
- **Have Set up commit in the primary checkout.** That commits on the human's branch without a review, and the only such commit stays a saved requirement file (ADR-004).
