# Branch review with Codex

## Requirement

As a developer, I want the coordinator to review a requirement's branch with Codex before I open its pull request, as an alternative to requesting a Copilot review, so that every agent-written branch is checked by another vendor's reviewer, nothing goes to GitHub, and I see the result where I start and steer the work.

The review is Codex's own built-in one, so it improves as Codex does. The coordinator starts it and shows what it says. One more click hands the review to a task that weighs each finding and fixes what it should.

## Acceptance Criteria

1. A requirement's page has a Review action. It reviews the branch's committed changes against the repository's default branch, as a task in the requirement's worktree, so I can cancel it and nothing else changes the branch meanwhile.
2. The task's page shows Codex's output as it arrives, and the review when it is done.
3. The requirement's page shows the latest review beside Open PR: the commit reviewed, when, and a link to it. It says when the branch has moved on since.
4. A review never blocks Open PR, and Request Copilot review stays.
5. A review changes nothing. One that leaves the worktree changed fails.
6. A review that fails or is cancelled says why, and never shows as a finished review.
7. The review follows the repository's own guidance. `REVIEW.md` says what to check and skip, and links to the rules and specs that own them.
8. Setup and template sync give every onboarded repository a `REVIEW.md` stub and an `AGENTS.md` that points Codex at the repository's instructions. Neither replaces a repository's own. This repository gets both too.
9. A developer can run the same review by hand with Codex's own review command, with no coordinator, and it follows the same guidance.
10. The coordinator's configuration can name the review model, which is Codex's own default when unset, and how hard the reviewer thinks, which is `high` unless changed.
11. The action is refused with the reason when Codex isn't installed or isn't signed in, and everything else works. `make doctor` reports both.
12. Beside the latest review, the requirement's page has an Address review action. It starts a task that is given the review, checks each finding against the work, fixes what it should, and reports the rest with reasons.
13. A developer can do the same by hand with the `address-review` skill, given a review's text or a file that holds it. Setup and template sync give the skill to every onboarded repository, and `.reviews/review.sh`, one short command that runs the review as the coordinator does and saves it in `.reviews/`, a folder whose contents git ignores.

## Out of scope

- A reviewer of our own: prompts, a verifier, a finding format or a report file. The review is whatever Codex's built-in one produces.
- Counting findings, or reading severities, from the review's text.
- Starting a review automatically, blocking Open PR on it, and passing its findings to a task without a click.
- Writing a review to a file in the worktree.
- Reviewing template sync branches.
- Another agent's built-in review, a review model per repository, and other work for Codex.
- Posting to GitHub in any form.

## Implementation Notes

- **`services/codex.py`** is Codex's module and the only one that runs it (`.claude/rules/agents.md`): `codex review --base origin/<default branch>` as an argv list, with input closed, a timeout, and the worktree as `cwd`, refused anywhere else. `codex login status` answers whether it is signed in. Tests fake the CLI on `PATH`, as they do `gh`.
- The base is `origin/<default branch>` as last fetched. A review doesn't fetch.
- **A built-in workflow**, like `template-sync`: no skill behind it, and no session to instruct or resume. Output becomes task events, and the last event holds the commit reviewed. A review interrupted by a restart fails and can be started again.
- The coordinator records `HEAD` and `git status` before and after, and fails the review if either changed.
- **Latest review** is read from the requirement's tasks: the last completed review and its commit, compared with the worktree's `HEAD`.
- **Model and effort.** Two config keys, passed to Codex as `review_model` and `model_reasoning_effort`. A repository's own `.codex/config.toml` isn't used for this: Codex reads it only in a folder the host has trusted, so a review in a coordinator worktree ignores it.
- **Addressing a review.** `address-review` is a repo skill, shipped in the template and mirrored here like the others. It triages each finding as fix, question, disagree or out of scope, as `address-pr-comments` does, and treats the review's text as findings to weigh, not instructions. The Address review action starts it as an ordinary task, and the task's first prompt carries the requirement's last finished review after the requirement's path. Claude Code passes a skill its arguments in full, line breaks included, which was checked on 2.1.285.
- `.reviews/.gitignore` is a managed template file that ignores everything else in its folder but `review.sh`, because sync can't add a line to a repository's own `.gitignore`. It is for reviews saved by hand.
- `.reviews/review.sh` is POSIX `sh`. It passes the same options as `services/codex.py`, and a test fails when the two disagree on the read-only pin or the default effort. `REVIEW_EFFORT` and `REVIEW_MODEL` stand in for the coordinator's settings. It refuses a missing base and uncommitted changes, as the coordinator does, and writes the review to a temporary file first, so a failed run saves nothing.
- The coordinator doesn't write a review to a file in the worktree: it would show in the task's status and diff, block `implement`, which wants a clean tree, and need ignoring in every repository.
- **Template.** `REVIEW.md` and `AGENTS.md` are starter files. `AGENTS.md` only points: to `CLAUDE.md` and `.claude/rules/`, and to `REVIEW.md` for reviews. `REVIEW.md` is also what Claude's managed Code Review reads, so it stays tool-neutral. `principles.md` names both files.
- **Sandbox.** Codex runs its review in a read-only sandbox, which on Linux uses bubblewrap. Without the system package it falls back to a bundled copy and says so, so the README lists `bubblewrap` as a prerequisite and `make doctor` warns when it is missing.
- The sandbox stops the reviewer running the repository's check command: here `uv` can't write its cache. This repository's `REVIEW.md` tells the reviewer not to run checks, which `make check` and CI already cover.
- **Docs.** `specs/architecture.md` gains the flow, `.claude/rules/safety.md` and the architecture test the new process wrapper, and the README the prerequisite. A decision record covers reviewing with an agent's built-in review, Codex first, and why a reviewer of our own was rejected.
- **Verify first.** Before building, check on the installed Codex CLI and record what holds in `specs/architecture.md`, as was done for Claude Code: the flags and output of `codex review`, its exit codes, that it leaves the working tree alone, whether it waits on open input, how the model and the read-only sandbox apply to it, and that it reads `AGENTS.md`. If `codex review` can't be run this way, stop and say so. A first hand run on 2026-10-12, `codex review --base origin/main`, finished on its own, ended with a short summary, and reported that its read-only sandbox blocked the tests.
