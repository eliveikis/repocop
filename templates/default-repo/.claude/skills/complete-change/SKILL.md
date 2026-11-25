---
name: complete-change
description: Close out a delivered change — fold its lasting design into the root and area specs, sparingly, then archive the change file. Use when a change in specs/changes/todo/ is fully delivered, or when asked to fold in, archive, or complete a change.
argument-hint: "[path-to-change.md]  (defaults to the branch's requirement)"
---
<!-- managed by template -->

# Complete change

Complete: `$ARGUMENTS`

With no path, complete the branch's requirement: the change in `specs/changes/todo/` the branch belongs to (`.claude/rules/specs.md` › A branch's requirement). If it belongs to none, say so, ask for the path, and change nothing. Name the change you picked before you start.

Run this on the change's own branch once its work is done, so the fold-in and the archive land in the same PR as the work. It only finalizes the change: it doesn't go over the acceptance criteria again, which the work's own tests and reviews already did.

## Preconditions (stop and report if any fail)

- You are **not** on `main`/`master`.
- `git status` is clean.
- The check command documented in `CLAUDE.md` (e.g. `make check`) is green, if the repo has one.

## Process

1. **Read.** Read the change in full, then `specs/index.md` and the root design files and area specs it lists. See what was already folded in while the change was being built: `git diff $(git merge-base main HEAD) -- specs/` (use the repo's default branch if it isn't `main`).
2. **Find the remainder.** List what the change's Requirement and acceptance criteria establish that the specs don't say yet, and what the specs say that the change made wrong. This list is usually short, because decisions should have been recorded as they were made.
3. **Fold in sparingly.** Only what the Requirement and its criteria establish goes into the specs, at the level `.claude/rules/specs.md` › What a spec says sets, and nothing from the change's Implementation Notes: the mechanism they settle is the work's own, stated in its docs and checks.
   - **Where it goes.** A feature's behaviour goes in the area spec it belongs to, never in `specs/architecture.md`. When it fits none, step 4 comes first.
   - **Leave in the archive:** implementation plans, acceptance-criteria checklists, test plans, the debate behind resolved questions (the outcome goes in the specs), file and function inventories (the repo itself is the truth for those), and anything the specs already cover.
   - **Edit in place.** Rewrite the section so it describes the system as it now is, and delete text the change made obsolete. Never append history such as "req-N added…".
   - **Decision records.** For each architecturally significant choice the change made that has no record yet, write one (`.claude/rules/specs.md` › Decision records).
   - **Product file.** Touch `specs/product.md` only for its roadmap row, or when the change genuinely shifted the vision, pillars, audience, or non-goals.
4. **Ask where behaviour goes when no area fits.** When the change brings behaviour that fits none of the area specs and doesn't say where it goes, ask the developer whether it goes in an existing area spec or a new `specs/<area>.md`, for a broad area the repository lacks (`.claude/rules/specs.md` › Area specs). Link a new one from `specs/index.md`, and from `specs/architecture.md` as `.claude/rules/specs.md` › Root design files says. Follow `.claude/rules/specs.md` (Mermaid diagrams, `_TBD: …_` markers).
5. **Archive.**
   - Run `.claude/skills/complete-change/archive.sh <path of the change>`. It moves the change into the `archive/` folder beside its folder, its name stamped with the UTC date and time (`specs/changes/todo/<file>` → `specs/changes/archive/<stamp>-<file>`), and prints the new path, then every line that still mentions the old one.
   - Fix those mentions. Remove the ones in specs, rules and skills, which must stand without archived changes, and point any others at the new path. Update status notes that still call it current (e.g. in `CLAUDE.md`).
   - Don't edit the archived file itself.
6. **Self-review.** Before committing, read the whole diff (`git diff HEAD`, and any new files) against `.claude/rules/principles.md` and the rules whose `paths` cover the files it touches. Tests can't catch most of what they say. Fix what breaks them, re-run the check command if you change anything, and say in the report what you checked and fixed.
7. **Commit** the fold-in and the archive together, as `.claude/rules/commits.md` says, naming the change by its file name, e.g. `Complete bulk-import`. Its body is the change's summary for its pull request: one or two sentences saying why the change was made and what it does, from its Requirement, then one line per place the work landed (a spec's section, a skill, a module), pointers rather than explanations. Nothing on how it was checked or reviewed.
8. **Do not** push or open a PR unless the human asked.

## Final report

- **Folded in:** one line per item (file › section: what changed)
- **Left in the archive on purpose:** one line per notable item, so the human can overrule
- New area spec, if any, and the developer's answer that placed it
- Self-review: what the diff was read against, and what that fixed
- The commit, and any links you couldn't resolve
