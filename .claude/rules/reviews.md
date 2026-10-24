<!-- managed by template -->
# Reviews

What every review of a branch checks. A repository's own points are in its `REVIEW.md`.

- A branch belongs to a requirement when it adds or edits one under `specs/changes/`, or when its name ends with a requirement's slug, as `agent/bulk-import` and `bulk-import` both do for `bulk-import.md`. Read that requirement for what the change should do and what it rules out.
- Report where the work contradicts it. Don't check its acceptance criteria one by one: running the product (its tests and the requirement's own checks) does that.
- Note work beyond the requirement in the review's summary, not as a defect. Sound, useful work can stay: whoever addresses the review judges.
- Report agent attribution in the branch's commits or its pull request, which `.claude/rules/commits.md` rules out.
- Report a bug fix in a tested layer that comes without a test that would have caught it. Don't ask for tests `.claude/rules/test-policy.md` doesn't call for.
