# Repositories

The developer registers each of their repositories once, and RepoCop then shows where it stands on every page load: whether its checkout is there, whether it is in step with the repo template, and what state the checkout is in. A repository is a primary checkout the developer owns, at `<repos_root>/<name>`, and the worktrees RepoCop makes for its template syncs, under `<worktrees_root>/<name>/`. RepoCop's only writes there are a fetch and a request to one of its sessions ([sessions.md › Session requests](sessions.md#session-requests)), each on the developer's click (`.claude/rules/safety.md` › Human-owned checkout).

## Adding a repository

- **From its remote or its checkout.** Adding has a page of its own, reached from the main page's head and the sidebar, which also shows the host paths. It takes a remote URL (accepted forms: `.claude/rules/safety.md` › Git remotes), or the name of a checkout already at `<repos_root>/<name>`, whose `origin` is then used. The name sets the paths.
- **The default branch is chosen, never guessed.** Adding takes two steps. The first shows what adding does, clone or register, and asks which branch is the default, from `origin`'s branches, with the one `origin` names already picked. `origin` is asked directly, which writes nothing, and a checkout whose `origin` can't be reached offers its branches as last fetched. For a remote with no branches yet, the user names the branch its first commit will go on. Nothing is cloned or recorded before the second step. Everything that compares with the default branch on `origin` uses this choice: the template status and sync, the board, and a sync's pull request. The repository's page shows it, and changes it to another of `origin`'s branches as last fetched.
- **No duplicates.** Remotes compare by identity, whatever their spelling.
- **Existing checkouts are registered, never changed**, and only when their `origin` matches. Otherwise RepoCop clones, inside the add request.
- **Adding writes nothing into the checkout.** A new repository gets the template's files through a [template sync](template-sync.md), like any other.

## Status

A repository's status is read on each page load:

| Status | When |
|--------|------|
| `missing` | the recorded path isn't a real folder inside `repos_root` holding a checkout of the registered remote. Git never runs in a path that fails this check |
| `no_commits` | the checkout has no commit yet, shown as needing one |
| `behind` the template | the default branch on `origin`, as last fetched, lacks a template file, has one that differs, a merged file that is behind or a marked file the template no longer ships, or can't be compared. It links to the repository's Sync page or, while a finished sync waits to land, to that sync ([template-sync.md › Waiting to land](template-sync.md#waiting-to-land)) |
| `ready` | otherwise |

It comes from the same comparison a sync plans with, which reads that branch, so neither uncommitted files nor the checkout's own branches hide the need to sync or create one. It reads only what the checkout already has: a partial clone that lacks a file on that branch is never made to download it on a page load, and its Sync page says it couldn't be read.

## Checkout state

Every checkout that isn't `missing` shows its state, read from git on each page load: the branch or detached commit, an unfinished merge or rebase, the files with uncommitted changes, and the commits ahead of and behind the branch's upstream as last fetched. Nothing is stored, and reading it never rewrites the checkout's index. A git failure is shown for that repository alone.

## Fetch

- **Only on a click.** A button on the repository's page fetches `origin` in the primary checkout, which changes its remote-tracking branches and nothing else. No page load fetches, and nothing fetches in the background.
- **A new default branch is offered, never taken.** After fetching, RepoCop asks `origin` which branch it names as its default. When that's not the repository's, the page offers to switch, and Fetch all lists it: nothing switches on its own.
- **Fetch all** on the main page does the same for every repository whose checkout is there, side by side, and shows each one's result: one failing doesn't stop the others.
- **Nothing waits for input.** Git never prompts, and every call has a timeout, so a missing credential or an unknown host key fails fast with git's own message instead of hanging.

## Remote links

A repository's remote is shown as its checkout's `origin` has it now, read from git on each page load, so another spelling of the registered remote set since, such as ssh for https, shows as it is. While the checkout is missing, the remote it was registered with is shown. It links to the repository's page on its host, `https://<host>/<path>`, which is where GitHub and hosts laid out like it serve it. A local remote is shown without a link.
