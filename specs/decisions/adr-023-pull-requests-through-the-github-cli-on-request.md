# ADR-023: Pull requests through the GitHub CLI, on request

**Status:** accepted · **Date:** 2026-10-05

## Context

When work on a coordinator branch is finished, the human pushed the branch, opened a pull request and asked for a review by hand, for a requirement's branch and for a template sync's. Doing that from the coordinator needs two things it didn't have: a push, which is the first coordinator write that leaves the machine, and a way to talk to GitHub.

## Decision

- GitHub is reached through the `gh` CLI, behind `services/github.py`, the only module that runs it. `gh` is found on `PATH` and uses the login `gh auth login` stored. The coordinator holds no GitHub credential.
- Only repositories on github.com are served.
- There are three actions, each run once per explicit click: open a pull request, which pushes the branch first; push; and ask Copilot for a review. No task, status change or page load pushes or calls GitHub.
- A push sends one branch the coordinator created to `origin` under the same name, and is never forced.
- Every action is refused before anything leaves the machine when it isn't safe: `.claude/rules/safety.md` › Pushing.
- The database keeps only the address of the pull request a branch last had open, by repository and branch.
- Merging, closing and approving stay on GitHub.

## Consequences

- `gh` is optional. Without it, or logged out, only these actions are refused.
- The calls run inside the request, with a timeout, as a fetch and onboarding's clone do (ADR-015).
- The coordinator doesn't follow a pull request between clicks, so the one a page shows may since be merged or closed. Every action asks GitHub first for the branch's open pull request and remembers it. Opening is refused while one is open, pushing and asking for a review are refused once none is, and a new one can then be opened from the same branch.
- When the remote branch has commits the worktree's lacks, the human brings them into the worktree before the coordinator can push again.
- Tests run a fake `gh` from `PATH` and push to a local bare repository, so the default suite never reaches GitHub.

## Alternatives rejected

- **GitHub's API with a token in the coordinator's configuration.** A second credential to store and protect, when `gh` already holds one and the repo's skills already use it.
- **Pushing when a task completes.** It publishes work nobody has looked at, and takes a decision the human keeps.
- **Forcing a push when the remote branch differs.** It can discard someone else's commits.
