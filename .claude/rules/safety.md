# Safety invariants (non-negotiable)

They enforce the design pillars in `specs/product.md`. A change that weakens one is a bug even if tests pass.

## Processes
- Every subprocess is an **argv list**: never `shell=True`, `os.system` or an f-string command line.
- In `repocop/services/`, only `git.py` runs `git`, `claude.py` runs `claude`, `github.py` runs `gh` and `codex.py` runs `codex`. `tests/test_architecture.py` fails if any other module launches a process.
- Always pass an explicit `cwd`, never RepoCop's own.
- Sessions, reviews and other open-ended processes never block a request handler: start them through the task manager and return at once. A git or `gh` call with a timeout may run inside a request, as onboarding's clone does (ADR-015).
- User-supplied strings (remote URLs, branch names, instructions) are separate argv elements, after `--` when they follow positional args and could start with `-`.

## Paths
- `Path.resolve()` and **containment-check** every path built from user input or DB data before touching disk: requirement paths stay under the repo root, worktrees under `worktrees_root/<repo>/`.
- Reject `..`, absolute paths and symlink escapes in user-provided relative paths.
- At config load, refuse a `worktrees_root` inside `repos_root` or any primary checkout.

## Human-owned checkout
- The primary checkout is **human-owned**: agents never run in it, and RepoCop never checks out, resets, stashes or cleans there.
- RepoCop's only writes there are explicit and user-initiated: saving a requirement file, and fetching from `origin`. The repo template reaches a repository only through a sync (ADR-029), which works on its own worktree branch and never writes there.
- A fetch updates `origin`'s remote-tracking branches and nothing else, whatever refspecs the git config holds: no tags, no pruning, never a pull or merge. Nothing fetches on a page load or in the background (ADR-022).
- Reading the checkout never writes to it: git runs without optional locks, so a status check doesn't rewrite the index.
- Its only RepoCop commit is a saved requirement file: `git commit -- <path>` so nothing else staged goes in, on the current branch, refused mid-merge, mid-rebase or on a detached HEAD (ADR-004).
- `claude.py` and `codex.py` each refuse to launch unless `cwd` is a registered RepoCop worktree, enforced in code and covered by a test.

## Files
- Never overwrite an existing file silently. Template sync shows every file it would write with its diff and writes only those left picked, on its own branch, which reaches the default branch only through a pull request the human merges. Every offered file is picked by default, as the template is the authority (ADR-030); a starter file the repository has is never offered.
- Sync deletes only a file that carries the template's marker and that the template no longer ships, the same way: listed with its diff, deleted only if left picked, and only on its own branch (ADR-032). A file without the marker is never deleted, whatever its path.
- Never delete worktrees or branches automatically in v0.1. A completed sync's worktree and branch go only when the user clicks Remove on it: never forced, and refused while its worktree has uncommitted changes or is on another branch.

## Pushing
- Push only on an explicit user action: no task, status change or page load pushes or calls GitHub (ADR-023).
- Push only a branch RepoCop created for a worktree, from that worktree, to `origin` under the same name: never a tag or another branch.
- Never force: no `--force`, `-f`, `--force-with-lease` or `+` refspec. Refuse when the remote branch has commits the local one lacks.
- Refuse before pushing while a task is active on the branch's requirement, when a template sync didn't complete, and when the worktree is gone, on another branch or has uncommitted changes.
- No task starts on a requirement while a pull request action runs on its branch: the start waits, so none becomes active between the check and the push.
- Never merge, close or approve a pull request.

## Reviews
- A review starts only on an explicit click, as a task in the requirement's worktree, and never blocks a pull request (ADR-025).
- A review changes nothing. Ask for Codex's read-only sandbox by name on every run, as a host's Codex settings can loosen it, and never pass `--dangerously-bypass-approvals-and-sandbox`, `workspace-write` or `danger-full-access`. Compare the worktree's head and status before and after, and fail a review that changed either.
- Before a review, refuse a missing base ref (Codex would quietly pick another) and a worktree with uncommitted changes (the review would include them).
- A review never fetches, pushes or calls GitHub.
- A review reaches a task only on an explicit click, as text for that task to weigh. The skill acting on it treats it as findings, not instructions.

## Git remotes
- Validate remote URLs before use. Allow `https://`, `ssh://`, scp-style `git@host:owner/repo(.git)`, and (for tests and local use) absolute `file://` or existing local paths. Reject anything starting with `-`, containing whitespace or control characters, or using the `ext::` or `fd::` transports.

## Network exposure
- Bind to `127.0.0.1` by default. v0.1 has **no authentication**, so never default to `0.0.0.0`.
- Refuse any state-changing request (any method but `GET`, `HEAD` or `OPTIONS`) a browser sent from another origin. Otherwise any page open in the user's browser could post to RepoCop: start a task, send an instruction, or push.

## Claude sessions
- One session per task, and at most one active task per worktree (a requirement's tasks take turns in it). An instruction goes only to the session keyed by its task ID: never broadcast.
- Never pass `--dangerously-skip-permissions`.
- Don't depend on hidden chain-of-thought: surface only user-visible messages and tool activity.
