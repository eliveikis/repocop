---
name: address-pr-comments
description: Fetch a GitHub pull request's review feedback (unresolved threads, review summaries, conversation comments) and address each finding with code changes or a reasoned reply. Use when asked to address, fix, or respond to PR review feedback.
argument-hint: "[pr-number]  (defaults to the PR for the current branch)"
---
<!-- managed by template -->

# Address PR comments

Target PR: `$ARGUMENTS` (if empty, the PR for the current branch).

Requires the `gh` CLI, authenticated. If it's missing, stop and say so.

## Steps

1. **Collect.** Run `.claude/skills/address-pr-comments/fetch-threads.sh [<n>]`. It prints the PR's branch, its unresolved review threads with a short diff excerpt, outdated unresolved threads in brief, review summaries, and conversation comments, as compact Markdown. Resolved threads, minimized comments, and bot conversation comments are already filtered out. Don't re-fetch with raw `gh api` unless the script fails.

   Act on every finding, wherever it appears: unresolved threads, points made only in review summaries (reviewers often list findings there that they didn't post as threads), and conversation comments. For outdated threads, check whether the point still applies to the current code.
2. **Confirm the branch.** The current branch must equal the `Branch:` the script printed. If it doesn't, stop.
3. **Triage.** Build a table: finding (thread, summary, or conversation) → classification (`fix`, `question`, `disagree`, `out-of-scope`) → planned action. Group related comments.
4. **Fix.** Make the minimal change per `fix` item and add or adjust tests where behaviour changes. Follow `CLAUDE.md` and `.claude/rules/`.
5. **Verify.** Run the check command documented in `CLAUDE.md` (e.g. `make check`), if the repo has one, until it's green.
6. **Self-review.** Before committing, read the whole diff (`git diff HEAD`, and any new files) against `.claude/rules/principles.md` and the rules whose `paths` cover the files it touches. Tests can't catch most of what they say. Fix what breaks them, re-run the check command if you change anything, and say in the report what you checked and fixed.
7. **Commit** the fixes as one commit, as `.claude/rules/commits.md` says, with a body that names the comments it addresses.
8. **Do not** push, resolve threads, or post replies unless the human explicitly asked. Instead, draft the replies: one per thread, plus one PR conversation comment covering the summary and conversation findings.

## Final report

```markdown
| Finding (source · file:line / summary) | Action |
Commit: ...
Draft replies for `question` / `disagree` / `out-of-scope` items:
- ...
Check result: ...
Self-review: ...
```
