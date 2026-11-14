<!-- managed by template -->
# Reviews

What every review of a branch checks. A repository's own points are in its `REVIEW.md`.

- Read the requirement the branch belongs to (`.claude/rules/specs.md` › A branch's requirement) for what the change should do and what it rules out.
- Report where the work contradicts it. Don't check its acceptance criteria one by one: running the product (its tests and the requirement's own checks) does that.
- Note work beyond the requirement in the review's summary, not as a defect. Sound, useful work can stay: whoever addresses the review judges.
- Report agent attribution in the branch's commits or its pull request, which `.claude/rules/commits.md` rules out.
- Report a bug fix that comes without the test `.claude/rules/test-policy.md` says it keeps, and a new test that policy says belongs in an existing one or shouldn't be written. Don't ask for tests it doesn't call for.
