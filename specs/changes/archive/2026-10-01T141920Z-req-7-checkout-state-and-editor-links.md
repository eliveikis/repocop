# Checkout state and editor links

## Problem

The repository list and each repository's page show its remote, its paths and whether it's ready, but not what state its primary checkout is in: which branch is checked out, whether it has uncommitted changes, whether it's behind its remote. That state decides what the coordinator does next, because a saved requirement is committed on whatever branch is checked out and a requirement's worktree is cut from the checkout's HEAD (`specs/architecture.md` › Requirements, branches and worktrees). Today the human finds it out in a terminal.

To look at a checkout or a worktree, the human also copies its path off the page and opens an editor by hand.

## Goal

The coordinator's pages show the current git state of every primary checkout, and every checkout or worktree path they show opens in the human's editor with one click. The coordinator stays an observer of the human-owned checkout: the only thing it may do there on top of today is fetch, on an explicit click.

## Requirements

### 1. Checkout state

For every repository whose checkout isn't `missing`, the pages show:

- the checked-out branch, or "detached" with the short commit
- a merge, rebase, cherry-pick or revert left unfinished
- how many files have uncommitted changes (staged, modified or untracked)
- how many commits the branch is ahead of and behind its upstream, or that it has no upstream

The repository list shows this as a short summary per repository. The repository's page shows the same, plus the changed files by path.

Everything is read from git when the page is loaded, and nothing is stored (`specs/architecture.md` › Components: git facts are queried live). When git fails for one repository, that repository shows the reason and the rest of the page still renders.

Ahead and behind compare with the remote as it was last fetched. The page says so.

### 2. Fetch, on a click

The repository's page has a **Fetch** button. It runs `git fetch origin` in the primary checkout, with the same timeout and no-prompt behaviour as the coordinator's other network calls, then shows the page again. A failure is shown inline.

Nothing else fetches: no page load does, and nothing runs in the background. The fetch never prunes. Nothing in this change pulls, merges, rebases, checks out, stashes, or otherwise changes the checkout's working tree, index or local branches.

A fetch changes the checkout's remote-tracking refs, which makes it a new kind of coordinator write in a human-owned checkout. `.claude/rules/safety.md` › Human-owned checkout lists the writes that are allowed, so this change adds a user-initiated fetch to that list, and records the decision in `specs/decisions/`.

### 3. Editor links

A new optional setting, `editor_url`, holds a URL template containing `{path}`. When it's set, every primary checkout path and every worktree path shown on a page that exists on disk carries an **Open in editor** link: the template with the absolute path put in, percent-encoded except for `/`. That covers the repository list, the repository's page and the task page. The path keeps its human-owned or coordinator-owned label.

It's a plain link, opened by the browser's machine. The coordinator launches no process for it, which keeps the rule that only the git and Claude wrappers launch processes, and keeps the link working when the browser isn't on the coordinator's host (`specs/product.md` › Platform targets).

When the setting is unset, no link is shown. Loading the configuration rejects a value that doesn't contain `{path}` exactly once.

`coordinator.example.yaml` documents the setting with a working example for VS Code on a local host, in WSL, and over SSH (see open question 4).

## Acceptance Criteria

- The repository list shows, for each repository that isn't `missing`, its branch (or detached HEAD), any unfinished operation, the number of changed files, and commits ahead and behind its upstream or that it has none.
- The repository's page shows the same and lists the changed files.
- A `missing` repository shows no checkout state, and git isn't run in its path.
- A git failure for one repository is shown for that repository and doesn't break the page.
- Fetch runs `git fetch origin` in the primary checkout only on its button's POST, and the page then shows the new ahead and behind counts. A test proves that loading any page fetches nothing.
- A failed fetch is shown inline with git's reason, and a fetch that can't reach its remote ends at the timeout instead of hanging.
- After a fetch, the checkout's working tree, index, HEAD and local branches are unchanged, covered by a test.
- `.claude/rules/safety.md` lists a user-initiated fetch among the allowed writes in a human-owned checkout, and a decision record explains it.
- With `editor_url` set, the repository list, the repository's page and the task page link each checkout or worktree path that exists on disk to the template with the path substituted and encoded. With it unset, no link appears.
- No coordinator module launches an editor: `tests/test_architecture.py` still passes unchanged.
- Loading configuration with an `editor_url` that lacks `{path}`, or has it twice, fails with a readable error.
- `coordinator.example.yaml` and the README's configuration table document `editor_url`.

## Scope boundaries

Not part of this change:

- Pull, merge, rebase, checkout, stash or any other action on a primary checkout beyond the fetch.
- Fetching on page load, on a schedule, or in the background.
- Ahead, behind or push state of a requirement's worktree branch. Pushing is req-2.
- Live refresh of checkout state. The human reloads the page.
- Starting an editor from the coordinator's own process, detecting which editors are installed, or a per-repository editor setting.

## Open questions

Proposed defaults are marked **→**.

1. **Fetching in a human-owned checkout.** **→** Allowed on an explicit click, because it changes only remote-tracking refs. The alternative is no fetch at all: show ahead and behind as of the human's own last fetch. That needs no change to the safety rule, but the counts are stale until the human fetches in a terminal.
2. **When the last fetch was.** **→** Show it beside ahead and behind, read from the modification time of the checkout's `FETCH_HEAD`, and say nothing when that file doesn't exist. Nothing is stored.
3. **What ahead and behind compare with.** **→** The checked-out branch's own upstream. The alternative, always comparing with the default branch on `origin`, answers "how far is this from main" instead, which is a different question.
4. **VS Code's URL forms.** _TBD: confirm by hand that each of these opens the folder: `vscode://file{path}` (local), `vscode://vscode-remote/wsl+<distro>{path}` (WSL), `vscode://vscode-remote/ssh-remote+<host>{path}` (SSH)._ **→** Document the ones that work. The setting itself is editor-agnostic either way.
