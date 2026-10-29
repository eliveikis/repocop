# Safety invariants (non-negotiable)

They enforce the design pillars in `specs/product.md`. A change that weakens one is a bug even if tests pass.

## Processes
- Every subprocess is an **argv list**: never `shell=True`, `os.system` or an f-string command line.
- RepoCop launches no coding agent: no Claude Code session and no Codex review (ADR-039). In `repocop/services/`, only `git.py` runs `git` and `github.py` runs `gh`. `tests/test_architecture.py` fails if any other module launches a process, or anything imports an agent's SDK.
- Always pass an explicit `cwd`, never RepoCop's own.
- Every git and `gh` call has a timeout, so it may run inside the request that asks for it, as onboarding's clone does (ADR-015). Nothing open-ended runs.
- User-supplied strings (remote URLs, branch names) are separate argv elements, after `--` when they follow positional args and could start with `-`.

## Paths
- `Path.resolve()` and **containment-check** every path built from user input or DB data before touching disk: requirement paths stay under the repo root, worktrees under `worktrees_root/<repo>/`.
- Reject `..`, absolute paths and symlink escapes in user-provided relative paths.
- At config load, refuse a `worktrees_root` inside `repos_root` or any primary checkout.

## Human-owned checkout
- The primary checkout is **human-owned**: RepoCop never checks out, resets, stashes, cleans or commits there.
- RepoCop's only write there is explicit and user-initiated: fetching from `origin`. Requirements are read-only in RepoCop, written and committed by their developer (ADR-037). The repo template reaches a repository only through a sync (ADR-029), which works on its own worktree branch and never writes there.
- A fetch updates `origin`'s remote-tracking branches and nothing else, whatever refspecs the git config holds: no tags, no pruning, never a pull or merge. Nothing fetches on a page load or in the background (ADR-022).
- Reading the checkout never writes to it: git runs without optional locks, so a status check doesn't rewrite the index.

## Files
- Never overwrite an existing file silently. Template sync shows every file it would write with its diff and writes only those left picked, on its own branch, which reaches the default branch only through a pull request the human merges. Every offered file is picked by default, as the template is the authority (ADR-030); a starter file the repository has is never offered.
- Sync deletes only a file that carries the template's marker and that the template no longer ships, the same way: listed with its diff, deleted only if left picked, and only on its own branch (ADR-032). A file without the marker is never deleted, whatever its path.
- Never delete worktrees or branches automatically in v0.1. A completed sync's worktree and branch go only when the user clicks Remove on it: never forced, and refused while its worktree has uncommitted changes or is on another branch.

## Pushing
- Push only on an explicit user action: no sync, status change or page load pushes or writes to GitHub (ADR-023). A page may read from GitHub, as the main page's board reads open pull requests (ADR-038).
- Push only a completed template sync's branch, which RepoCop created for its worktree, from that worktree, to `origin` under the same name: never a tag or another branch.
- Never force: no `--force`, `-f`, `--force-with-lease` or `+` refspec. Refuse when the remote branch has commits the local one lacks.
- Refuse before pushing when the template sync didn't complete, and when its worktree is gone, on another branch or has uncommitted changes.
- Never merge, close or approve a pull request.

## Git remotes
- Validate remote URLs before use. Allow `https://`, `ssh://`, scp-style `git@host:owner/repo(.git)`, and (for tests and local use) absolute `file://` or existing local paths. Reject anything starting with `-`, containing whitespace or control characters, or using the `ext::` or `fd::` transports.

## Network exposure
- Bind to `127.0.0.1` by default. v0.1 has **no authentication**, so never default to `0.0.0.0`.
- Refuse any state-changing request (any method but `GET`, `HEAD` or `OPTIONS`) a browser sent from another origin. Otherwise any page open in the user's browser could post to RepoCop: sync a repository, remove a sync, or push.
