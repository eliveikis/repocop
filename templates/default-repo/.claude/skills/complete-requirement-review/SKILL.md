---
name: complete-requirement-review
description: Record a requirement's last saved review as complete over the requirement's text as it now stands, so it counts as ready to implement, without reviewing it again. Use when the changes a requirement's review discussed have been made and the developer asks to complete, close or accept that review.
argument-hint: "[path-to-requirement.md]  (defaults to the branch's requirement)"
allowed-tools: Read, Glob, Bash(git branch --show-current), Bash(git rev-parse:*), Bash(.claude/skills/review-requirement/save-review.sh:*)
---
<!-- managed by template -->

# Complete requirement review

Complete the review of the requirement at `$ARGUMENTS`. With no path, complete the review of the branch's requirement: the change in `specs/changes/todo/` the branch belongs to (`.claude/rules/specs.md` › A branch's requirement). If it belongs to none, say so and ask for the path. Name the requirement you picked before you start.

Completing a review records the developer's word that the changes it discussed are made, so the requirement is ready to implement as its text now stands. It saves the requirement's last saved review again, over the file as it is now, with the verdict `yes` and no blocking questions. That save is its one write, outside every commit: don't edit or commit anything, and don't review the requirement or check that its changes answer the review. The developer's word settles it.

## Steps

1. **Read the last saved review.** It is `repocop/reviews/<requirement's file name>` in the git folder `git rev-parse --path-format=absolute --git-common-dir` prints. The file starts with a header between `---` lines, whose `requirement` is the requirement's path from the checkout's top, and the review follows it. If there is no such file, or its header names another path, the requirement has no saved review: say so, save nothing, and stop.
2. **Write the note** that the review was completed, under a `## Review completed` heading. When this session changed the requirement to apply the review, list what it applied, one item each. Otherwise, write that the developer marked the review complete.
3. **Save it.** Pass the review, exactly as it follows the header, then a blank line and the note, on standard input to `.claude/skills/review-requirement/save-review.sh`, with the requirement's path from the checkout's top, the verdict `yes` and `0` blocking questions:

   ```sh
   .claude/skills/review-requirement/save-review.sh specs/changes/todo/bulk-import.md yes 0 <<'END_OF_REVIEW'
   ## Summary
   ...

   ## Review completed

   - Answered blocking question 1: imports read CSV only.
   END_OF_REVIEW
   ```

   It records the file as it is now and replaces the last saved review. End with the saved file as a Markdown link to the path the script printed, such as `[bulk-import.md](/home/dev/shop/.git/repocop/reviews/bulk-import.md)`, so it opens with a click: editors hide the git folder it's in from their file lists and search. If the script refuses, say why.
