<!-- managed by template -->
# Commits

- Commit when the human asks or a skill's work is done, not while discussion is still shaping the work.
- One commit per change: a requirement delivered, a review addressed, a change completed. Related edits, even several groups of them, go in one commit; split off only a large part that stands on its own for review.
- A follow-up to your own unpushed commit for the same work goes into it (`git commit --amend`). Once pushed, add a new commit: never rewrite what is pushed. Check, don't assume: an editor can push a branch for you. `.claude/hooks/amend-only-unpushed.sh` refuses an amend of a commit already on a remote-tracking branch.
- Subject: imperative, saying what the change does. Body: why, and any design choice that has no decision record.
- No agent attribution in commits or pull requests: no `Co-Authored-By` trailer, "Generated with" line or other credit to an AI agent or tool. Remove one from a commit that isn't pushed yet, and from a pull request's description; a pushed commit keeps it, since pushed history is never rewritten.
