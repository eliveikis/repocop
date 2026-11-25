# ADR-044: RepoCop removes a merged branch and its worktree on the developer's confirmation

**Status:** accepted · **Date:** 2026-11-25

## Context

Every requirement the developer's agent delivers leaves its worktree and local branch behind once its pull request is merged, and across a fleet they pile up: folders no one works in, and branch lists full of finished work. Until now RepoCop deleted nothing in a repository but a template sync's own branch and worktree, on a click (ADR-006), and its writes in a human-owned checkout were a fetch (ADR-022) and a request to a session (ADR-041). Clearing finished branches by hand is tedious, and the usual shortcut, deleting every branch whose remote branch is gone, loses work: a remote branch also goes when its pull request is closed unmerged or someone deletes it, and the developer may have committed after the merge. RepoCop already reads each repository's pull requests from GitHub (ADR-038) and knows which sessions are live (ADR-040).

Some agent tools keep their worktrees inside the primary checkout's own folder, so removing one deletes a folder there.

## Decision

- **A branch is merged only by GitHub's word and the branch's tip.** GitHub reports a pull request from it, in the registered repository, as merged, and the local branch's tip is that pull request's last commit. A squash merge counts; a branch committed to since doesn't; nothing else does, not even a branch the default branch already contains, since a branch just made from it looks the same.
- **Removal is a write in the human's checkout, made only on confirmation.** It joins the fetch and the session request as the writes RepoCop makes there: the repository's page lists the merged branches with their worktrees, and removes the ones the developer picks only after showing what goes, the ignored files in each worktree included, and getting their confirmation. Nothing removes a branch on a page load, a fetch, a refresh or a timer.
- **Each branch is checked again at the click and refused where work would be lost:** a worktree with modified or untracked files, a lock, a session in it that isn't closed, a branch checked out in the primary checkout, or a tip that is no longer the merged pull request's last commit. The worktree goes as `git worktree remove` does without forcing; the branch, which a squash merge leaves uncontained, goes with `-D` right after that check.
- **A worktree inside the primary checkout's folder is the worktree's, not the checkout's.** Git lists it as a working tree of its own, and the checkout's tracked files, index, HEAD and branches are untouched by its removal, so removing it on confirmation is this write and no other. The primary checkout itself, a path that holds it, or a link, is never removed.
- **Nothing else goes:** no branch on GitHub, whose own setting deletes them, no remote-tracking branch, since a fetch never prunes, and nothing in the repository's git folder that RepoCop or the template's hook keeps.

This supersedes the part of ADR-039 that said the worktrees and branches of past runs stay untouched as RepoCop never deletes them: those a merged pull request finished now go on confirmation.

## Consequences

- `CLAUDE.md`'s first and third invariants, `.claude/rules/safety.md` and the first and third pillars in `specs/product.md` name this write beside the fetch and the session request.
- A branch merged outside GitHub, fast-forwarded by hand or closed unmerged stays until the developer deletes it themselves: RepoCop can't tell its work is safe.
- A worktree's `.env` or `.venv/` goes with it, so the confirmation lists them.
- Only the newest merged pull requests are read, so a branch merged long ago isn't offered until the list says so and the developer deletes it by hand.

## Alternatives rejected

- **Deleting every branch whose remote-tracking branch is gone**, as `git fetch --prune` and a loop over `[gone]` branches do. It loses the work of a pull request closed unmerged, and of commits made after the merge.
- **Counting a branch the default branch contains as merged.** A branch just made from the default branch, with work about to start on it, is contained too.
- **Removing on a schedule or after a fetch.** A write in the human's checkout without a click breaks the first pillar.
- **Keeping worktrees inside the primary checkout's folder out of reach.** It leaves the very worktrees some agent tools make behind, and git already tells them apart from the checkout.
