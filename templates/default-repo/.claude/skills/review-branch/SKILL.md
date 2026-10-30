---
name: review-branch
description: Review the current branch's changes with the repository's own Codex review, read-only, and save the review in .reviews/. Use when asked to review a branch's work before its pull request.
argument-hint: "[base]  (defaults to the default branch on origin, as last fetched)"
---
<!-- managed by template -->

# Review branch

The base to review against: `$ARGUMENTS`

Review this branch's commits with `.reviews/review.sh`, the repository's own review: Codex's built-in review, read-only, against the base, which with nothing given is the default branch on `origin` as last fetched. Nothing is fetched, and nothing in the checkout changes. The script's header says how it runs, which options it holds, and where it saves the review.

## Steps

1. **Run it.** Run `.reviews/review.sh`, with the base if one was given, and nothing else around it: no options of your own, and no other review. It takes a while, and Codex's progress shows as it works.
2. **When it refuses**, as it does on the base's own branch, with uncommitted changes, with no commits the base lacks, and without Codex installed and signed in, report its reason as it gives it, and stop. Don't work around it: commit, switch branch or sign in only when the human asks.
3. **Don't act on the review.** It is one reviewer's opinion of the work: report it, and leave weighing and fixing its findings to whoever asks for that.

## Final report

- The file the review was saved in, such as `.reviews/<branch>-<commit>.md`
- What it found, briefly, in its own order of severity, or that it found nothing
- Or, when it refused, why
