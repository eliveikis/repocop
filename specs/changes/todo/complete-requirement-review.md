## Requirement

When the developer has their agent apply the changes a requirement's review discussed, the review is done: the requirement is ready, as its text now stands. Today RepoCop shows it as "Changed since review" until another review runs, which asks for a review with nothing left to find, and costs the developer time and tokens on every requirement. The repo template gains a skill, `/complete-requirement-review`, that records the review as complete over the requirement's text as it is now, so RepoCop shows it Ready. The developer's word settles it, as the human keeps final control (`specs/product.md` › Design pillars).

## Acceptance Criteria

1. The repo template ships a `complete-requirement-review` skill. Given a requirement's path, or with none the branch's requirement (`.claude/rules/specs.md` › A branch's requirement), it saves the requirement's review again, over its file as it is now, with the verdict `yes` and no blocking questions.
2. Once it has run, the requirement's page and its card show it Ready, with the review it saved and when it was saved.
3. The review it saves is the one last saved for the requirement, then a note that the review was completed: what was applied, when the session it runs in made the changes, or else that the developer marked it complete.
4. It edits nothing in the repository, commits nothing, and reviews nothing: it doesn't check that the changes answer the review.
5. It refuses, saying why and saving nothing, when the requirement has no saved review.
6. `specs/requirements.md` › A requirement's review says that a review the developer completes makes the requirement Ready on its text as it then is, in place of "There is no override".

## Out of scope

- Completing a review from RepoCop's own page. RepoCop writes no review, and a requirement's page can already ask one of its sessions to run the skill.
- Completing with any verdict but Ready.
- Any change to the standings: a requirement edited after its review, which no one completed, still shows "Changed since review".

## Implementation Notes

- The skill saves with `.claude/skills/review-requirement/save-review.sh`, which stays in its own skill's folder as the one writer of a saved review. The script works out the file's SHA-256 as it does for a review. `.claude/rules/principles.md` › Scripts live beside their only consumer gains the exception, in both copies: a script that is the one writer of a stored format serves each skill that writes it, from where it is.
- The skill reads the last saved review from `<git common dir>/repocop/reviews/<requirement's file name>`, the git folder from `git rev-parse --git-common-dir`. The settings already allow both commands. `tests/test_default_template.py` checks that the skill's commands are covered.
- Neither skill names the other (`.claude/rules/skills.md`). `review-requirement`'s text is unchanged.
- The skill is mirrored like the other skills, so RepoCop's own `.claude/skills/` gets the same copy.
- `specs/repo-template.md` (What every repository gets › Workflows) follows.
