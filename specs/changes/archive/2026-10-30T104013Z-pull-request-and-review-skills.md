## Requirement

Once `/implement` is done, the developer has the branch reviewed and opens its pull request. RepoCop's Review and Open PR buttons did that only for branches RepoCop made, and `no-agent-runs` removes them. By hand, the developer runs `.reviews/review.sh` and writes a pull request that knows less about the work than the agent that did it.

Two skills in the repo template do it in the agent's own session, where the work is in view:
- `/review-branch` runs the repository's own Codex review of the branch and saves it, for `/address-review` to pick up.
- `/open-pull-request` pushes the branch and opens its pull request, with a title and description written from the requirement and the work.

RepoCop can then send either one to a session in one click (`queue-next-step`), like any other workflow.

## Acceptance Criteria

1. `/review-branch` reviews the current branch as `.reviews/review.sh` does: read-only, against the default branch on `origin` as last fetched. It saves the review in `.reviews/` and reports what it found, changing nothing.
2. `/address-review`, given no argument, then addresses that review, as it already does with the latest saved review of the branch.
3. `/open-pull-request` pushes the branch to `origin` under the same name, never forced, and opens a pull request into the default branch. It is titled with what the change does, and its description says:
   - what the change does and why, from the requirement;
   - how it was checked;
   - which requirement it delivers, linked to its file.

   It carries no agent attribution (`.claude/rules/commits.md`).
4. When the branch already has an open pull request, `/open-pull-request` pushes the new commits and gives that pull request's link instead of opening a second.
5. Pushing, and opening the pull request, each ask the developer first, as the template's settings already have pushing ask.
6. Each skill refuses, saying why and changing nothing:
   - on the default branch;
   - with uncommitted changes;
   - with no commits the default branch lacks;
   - when its tool (`codex` or `gh`) is missing or not signed in.
7. Onboarded repositories get both skills through template sync, and RepoCop's own copies match the template's.

## Out of scope

- Merging, closing or approving a pull request.
- Asking for a review on GitHub, such as Copilot's.
- RepoCop's pages: `queue-next-step` offers committed skills already.

## Implementation Notes

- The template's allowlist gains:
  - `.reviews/review.sh`, and `gh auth status`, `gh pr list` and `gh pr view`, allowed;
  - `gh pr create` and `gh pr edit`, on "ask", beside `git push`.

  `tests/test_default_template.py` checks the skills' commands are covered.
- `/review-branch` leaves the review's options to `.reviews/review.sh`, which keeps them in step with what RepoCop ran (`tests/test_review_script.py`).
- `templates/README.md` and `specs/changes/README.md`'s lifecycle name the two steps.

## Open questions

1. **Draft or ready for review.** **→** Ready: the skill runs once the work is done. The alternative opens a draft, for a developer who wants to look before others do.
