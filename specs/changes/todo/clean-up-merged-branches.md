## Requirement

Every requirement the developer's agent delivers leaves its worktree and local branch behind after its pull request is merged, and across a fleet they pile up: folders no one works in, and branch lists full of finished work. Clearing them by hand is tedious, and the usual shortcut, deleting every branch whose remote branch is gone, loses work: a remote branch also goes when its pull request is closed unmerged or someone deletes it, and the developer may have committed after the merge. RepoCop already reads each repository's pull requests from GitHub and knows which sessions are live, so a repository's page lists the branches whose work is merged, with their worktrees, and removes the ones the developer picks, on their click, only where nothing would be lost.

A branch is **merged** here when GitHub reports a pull request from it, in the registered repository, merged, and the local branch's tip is that pull request's last commit, so a squash merge counts and a branch committed to since doesn't. Nothing else counts in this change.

## Acceptance Criteria

1. A repository's page lists its merged local branches: each with the pull request it was merged by, and the worktree it is checked out in, if any, wherever that worktree is.
2. A Delivered card whose requirement's branch is listed says its branch is still here, and links to the list. The board itself still acts on nothing.
3. Every listed branch is picked by default, and the developer can untick any. Remove shows what will go before anything does: each picked branch, its worktree, and the ignored files in that worktree that removing it deletes too, such as a `.env` or a `.venv/`. Nothing is removed until the developer confirms there.
4. On confirming, each picked branch's worktree is removed, then the local branch is deleted, and the page reports each branch as removed or refused, with why. One refusal doesn't stop the others.
5. A branch is refused, and its worktree and branch left as they were, when its worktree has modified or untracked files, is locked, or has a session in it that isn't Closed; when it is checked out in the primary checkout; and when its tip is no longer the merged pull request's last commit, as checked again at the click.
6. A worktree whose folder is already gone is listed with its branch, and removing it clears git's record of that worktree.
7. Nothing else is removed: no branch on GitHub, no remote-tracking branch, no worktree or branch the developer didn't confirm, and nothing in the repository's git folder that RepoCop or the template's hook keeps, such as session logs, workflow history and saved reviews.
8. Nothing is removed on a page load, a fetch, a refresh or a timer: only on the developer's confirmation.
9. Without the GitHub CLI, signed out, on a repository not on github.com, or with no answer in time, the list says why it can't be read, lists nothing, and the rest of the page still shows.
10. A template sync's branch isn't listed: its own page removes it.

## Out of scope

- Deleting branches on GitHub, which its "Automatically delete head branches" setting does.
- Removing anything on a schedule or on its own.
- Pruning remote-tracking branches: a fetch still never prunes.
- Branches with no merged pull request on GitHub: closed unmerged, merged outside GitHub, or fast-forwarded by hand.
- Cleaning up across every repository at once from the main page.

## Implementation Notes

- This reverses `specs/architecture.md`'s "RepoCop doesn't delete a merged branch or its worktree", and adds a write to the developer's repository beside the fetch and a request to a session: CLAUDE.md's invariant 1, `.claude/rules/safety.md` (Human-owned checkout, and Never delete worktrees or branches automatically) and `specs/product.md`'s pillars 1 and 3. Record it in a decision record, and update those in the same change.
- Remove a worktree as `git worktree remove` does without `--force`, which refuses modified and untracked files and a lock but deletes ignored files, hence the listing in 3. Delete the branch only after its worktree is gone. Since a squash-merged branch isn't contained in the default branch, `git branch -d` refuses it, so it takes `-D`, right after checking its tip again (5).
- Some agent tools keep their worktrees inside the primary checkout's folder. The decision record says whether removing one there counts as a write to the primary checkout, which RepoCop never makes.
- Read merged pull requests as the board reads open ones: one `gh pr list` per repository with the board's timeout, after the page renders, so the page never waits for GitHub.
- Find worktrees and branches from the primary checkout with read-only git calls (`git worktree list --porcelain`, `git for-each-ref`), a fixed number whatever their count. A worktree's path comes from git, not the user: containment-check it against git's own list before removing it.
- A session is in a worktree when its latest event's `cwd` is that worktree or a folder inside it.

## Open questions

1. How many merged pull requests are read per repository? **→** The newest 500. A branch merged longer ago isn't listed, and the list says when it reached that limit.
2. Does a branch the default branch on `origin` already contains, with no merged pull request, count as merged? **→** No: a branch just made from the default branch, with work about to start on it, looks the same.
3. Should the main page show how many merged branches each repository has left? **→** No: the repository's page and its Delivered cards are enough for this change.
