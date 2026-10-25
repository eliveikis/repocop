## Requirement

A developer working a requirement through its steps in their own session types the same path after every command: `/review-requirement`, `/implement`, `/address-review` and `/complete-change` each need `specs/changes/todo/<file>.md`, and `/address-review` a review file's path too, though the branch already says which requirement it's for. Typing them is slow, and a typo picks the wrong file.

Each of those skills works on the current branch's requirement when given no argument, as `/address-pr-comments` already finds the current branch's pull request. A path given explicitly still wins, for a branch whose name doesn't match or for work on another requirement.

## Acceptance Criteria

1. Given no argument, `/review-requirement`, `/implement` and `/complete-change` work on the branch's requirement: the change in `specs/changes/todo/` the branch belongs to, by the rule in `.claude/rules/specs.md` (criterion 5).
2. Given no argument, `/address-review` addresses the newest review of the branch saved in `.reviews/` (`.reviews/<branch>-<commit>.md`, the branch's `/` written `-`), against the branch's requirement.
3. An argument works as it does today, whatever the branch.
4. A skill that finds no requirement for the branch, or more than one, or for `/address-review` no saved review, says so and asks for the path, and changes nothing.
5. Which requirement a branch belongs to is stated once, in `.claude/rules/specs.md`, which the reviews rule and these skills point to.
6. Each of these skills names the requirement, and for `/address-review` the review file, it picked before it starts.
7. Onboarded repositories get the changed skills and rules through template sync.

## Out of scope

- A VS Code extension, or buttons on RepoCop's pages, for running the steps.
- Creating or switching branches.
- Changing RepoCop, which always passes a skill its paths.

## Implementation Notes

- The rule moves from `.claude/rules/reviews.md` to `.claude/rules/specs.md` as it stands: a branch belongs to a requirement when it adds or edits one under `specs/changes/`, or when its name ends with the requirement's name, as `agent/bulk-import` and `bulk-import` both do for `bulk-import.md`.
- The skills and both rules are copies of the repo template's (`MIRRORED` in `tests/test_default_template.py`), so each changes in both places.
