---
name: implement
description: Implement a requirement end-to-end on the current branch — plan, build each piece with its check written first, verify with the repo's check command, and summarize. Use when asked to implement a change in specs/changes/todo/.
argument-hint: "[path-to-requirement.md] [scope note]  (defaults to the branch's requirement)"
---
<!-- managed by template -->

# Implement

Implement: `$ARGUMENTS`

With no path, implement the branch's requirement: the change in `specs/changes/todo/` the branch belongs to (`.claude/rules/specs.md` › A branch's requirement). If it belongs to none, say so, ask for the path, and change nothing. Name the requirement you picked before you start.

## Preconditions (stop and report if any fail)

- You are **not** on `main`/`master`. Don't create or switch branches yourself: work on the branch you're on, which the human or RepoCop chose.
- The requirement file exists.
- `git status` is clean apart from the requirement file itself.

## Process

1. **Understand.** Read the requirement, `CLAUDE.md`, `.claude/rules/*`, `specs/index.md`, and the authoritative specs it lists. Identify the acceptance criteria still to meet, narrowed by the scope note if one was given. Judge what's already met from the repo itself, such as existing tests, not from marks in the change. If the requirement contradicts itself, the specs, or what's already in the repo in a way you can't settle, stop and ask a specific question instead of guessing.
2. **Plan.** Write a short numbered plan: files to touch, how each step will be checked, and the AC it satisfies. If the remaining work is too large to deliver well in one run, plan a coherent slice that later work builds on, and say what remains.
3. **Check first.** Before building a piece, write the check that shows it's done: automated where `.claude/rules/test-policy.md` says a test is worth it (in code, a failing test: make it pass, then refactor), otherwise a named manual check (tone, accuracy, how a piece reads or looks).
4. **Keep it small.** Follow the repo's existing patterns. Don't add dependencies, abstraction layers or other new structure, or anything out of scope (see the spec's scope boundaries).
5. **Verify.** Run the check command documented in `CLAUDE.md` (e.g. `make check`) until it is fully green, and make the manual checks from step 3. Don't claim success on a partial run. If the repo documents no check command, say so.
6. **Record.** Don't edit or move the requirement file: it's the human's statement of the work. If it proves wrong or incomplete, say what should change in your report. When a design decision was made or changed, update the authoritative spec it belongs to (`specs/architecture.md` or `specs/<area>.md`) right away, so the specs never lag the work. If the choice is significant and hard to reverse, also write a decision record in `specs/decisions/` (`.claude/rules/specs.md`). A criterion counts as met only when a test or a concrete manual step demonstrates it. When every criterion is met, say the change is fully delivered.
7. **Self-review.** Before committing, read the whole diff (`git diff HEAD`, and any new files) against `.claude/rules/principles.md` and the rules whose `paths` cover the files it touches. Tests can't catch most of what they say. Fix what breaks them, re-run the check command if you change anything, and say in the report what you checked and fixed.
8. **Commit** the change once it is done, as `.claude/rules/commits.md` says: one commit, with an imperative subject (`Add worktree path containment check`, `Draft the pricing section`) and a body that says why.

## Final report

- Each acceptance criterion: met, with the test or manual check that shows it, or not yet, and why
- What was deliberately left out or deferred
- Check result, with the test count if the repo has tests, and the manual checks made
- Self-review: what the diff was read against, and what that fixed
- Open questions or risks for the human
