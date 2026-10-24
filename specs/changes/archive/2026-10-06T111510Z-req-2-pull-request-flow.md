# Pull request flow

## Problem

After an agent finishes work on a requirement's branch, the human leaves the coordinator to finish the loop by hand: push the branch, open a pull request, and request a Copilot review. After `/address-pr-comments` commits fixes, they push again and re-request the review. These steps are the same every time, and they are the only routine steps of the review → implement → address feedback → complete loop that happen outside the coordinator.

A template sync ends the same way. It commits on its own branch and shows as completed, and its page offers no next step.

## Goal

From a requirement's page, or a completed template sync's page, the human can push its branch, open a pull request, get it reviewed by Copilot, and push follow-up commits, with one explicit click per step. Merging stays on GitHub, done by the human.

## Acceptance Criteria

### A. Actions

- Open PR pushes the branch with its upstream set and creates a PR into the default branch, titled with the requirement's name and linking the requirement file. The PR link appears on the requirement page.
- Push sends new commits to the existing PR branch.
- Request Copilot review adds `@copilot` as a reviewer on the stored PR.
- A completed template sync's page offers the same three actions for its branch, and says the branch is only on this machine until its PR is opened. The PR link appears on that page.
- Nothing is pushed or opened except by an explicit click. A test proves that no task or status transition triggers a push.

### B. Refusals

- Each action is refused with a visible reason, with a test per case, when:
  - a task is active on the requirement
  - the template sync didn't complete
  - the worktree has uncommitted changes
  - `origin` isn't a GitHub remote
  - the GitHub CLI is missing or not authenticated
  - (Open PR only) a PR already exists for the branch, in which case the page links to it instead
- No push argv ever contains `--force`, `-f`, or `--force-with-lease`, covered by a test.
- A diverged remote branch refuses Push with a visible reason.

### C. Hermetic tests

- Tests push to a local bare repository and use a fake `gh` on `PATH` (like `fake_claude`). The default test suite never calls GitHub.

### Other

1. **GitHub access.** **→** The `gh` CLI behind a `services/github.py` wrapper, recorded as an ADR next to ADR-001. It reuses `gh auth login` and the same tool the repo skills already use.
2. **PR body.** **→** Deterministic: a link to the requirement file.
3. **Draft or ready.** **→** Ready by default.
4. **A template sync's PR.** **→** Titled "Sync with the repo template", with the files it changed listed in the body.

### D. Operations

- `make doctor` reports whether `gh` is installed and authenticated, as optional: without it the coordinator still runs, and only these actions are disabled.

## Scope boundaries

Not part of this change:

- Merging, closing, or approving PRs from the coordinator. Merging stays on GitHub, and auto-merge remains a non-goal.
- GitLab, Bitbucket, or other hosts.
- Webhooks or background polling of PR state.
- Showing CI results.
- A Claude-written PR description.
- Recording the PR in the repo, for example in the requirement file.
- Deleting a branch or its worktree once the PR is merged.

