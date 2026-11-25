---
depends-on:
  - clean-up-merged-branches
---
## Requirement

Merged branches clears the worktrees of branches whose pull request GitHub merged, but some worktrees it never lists, and those pile up unseen. They include a worktree on a detached HEAD, as some agent tools make, a branch whose pull request was closed unmerged or that never had one, a branch merged outside GitHub or longer ago than the merged pull requests RepoCop reads, and every worktree of a repository not on github.com. The developer can't tell from RepoCop that they are there. So a repository's page lists every worktree the repository has, read from git alone, and removes the ones the developer picks, several at once, on their confirmation, only where nothing would be lost. A worktree goes, never its branch: the branch keeps every commit, so removing an unmerged branch's worktree loses no work.

## Acceptance Criteria

1. A repository's page lists each of its worktrees except the primary checkout and its template syncs' worktrees, wherever each is. A merged branch's worktree is listed too, as it is under Merged branches; removing it here leaves its branch, which Merged branches still lists. Each shows its path, its branch or the commit it is detached at, when it was last committed to, and the latest session in it with that session's state, if there is one. The least recently active come first.
2. The list shows with the page, without waiting for GitHub, both when GitHub can't be read and for a repository not on github.com.
3. A worktree whose folder is gone, or that is locked, says so.
4. None is picked by default. The developer picks any number of the listed worktrees, and Select all picks every one, which they can then untick one by one. Remove shows what will go before anything does: each picked worktree, and the ignored files in it that removing it deletes too, such as a `.env` or a `.venv/`. Nothing is removed until the developer confirms there.
5. On confirming, each picked worktree is removed and its branch stays. The page reports each worktree as removed or refused, with why, and one refusal doesn't stop the others.
6. A worktree is refused, and left as it was, as checked again at the click, when:
   - it has modified or untracked files;
   - it is locked;
   - it is in the middle of a merge, rebase, cherry-pick or bisect;
   - a session in it isn't Closed, including one quiet for longer than a session shows while its process still runs;
   - it holds another worktree;
   - it is the primary checkout;
   - it is detached at a commit that no branch, tag or remote-tracking branch contains;
   - what goes with it has changed since it was shown.
7. Removing a worktree whose folder is already gone clears git's record of it.
8. Nothing else is removed: no branch, local or remote-tracking, nothing on GitHub, no worktree the developer didn't confirm, and nothing in the repository's git folder that RepoCop or the template's hook keeps.
9. Nothing is removed on a page load, a fetch, a refresh or a timer: only on the developer's confirmation.

## Out of scope

- Deleting a branch from this list. Merged branches removes a merged branch with its worktree; an unmerged one stays until the developer deletes it.
- Deciding by age which worktrees are stale, or removing any on a schedule or on its own.
- Cleaning up across every repository at once from the main page.
- Pruning every stale record of a worktree at once, as `git worktree prune` does. Only the records the developer picks are cleared.

## Implementation Notes

- This widens ADR-044: a worktree with no merged pull request goes too, on confirmation, while its branch stays. Record that in a decision record that supersedes the part of ADR-044 it changes. In the same change, update CLAUDE.md's first and third invariants, `.claude/rules/safety.md` (Human-owned checkout, and Files) and the first and third pillars in `specs/product.md`.
- Remove a worktree the way Merged branches does, with the same refusals, the same preview and the same check that what goes is what was shown, but without deleting the branch, so those checks have one implementation.
- Read the list with a fixed number of git calls, whatever the number of worktrees: `git worktree list --porcelain`, and one call for the commit dates of every worktree's HEAD. Read status and ignored files only for the picked worktrees, at the preview and at the click.
- A detached commit is contained when `git rev-list <commit> --not --branches --tags --remotes` prints nothing.
- Tell a template sync's worktree by RepoCop's record of its syncs, as Merged branches leaves out a sync's branch.
