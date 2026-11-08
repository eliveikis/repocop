# ADR-043: A requirement's review saves its verdict, and RepoCop tells from it whether the requirement is ready

**Status:** accepted · **Date:** 2026-11-08

## Context

The developer loses track of which requirements have been through a review and are ready to implement. The history of workflow runs (ADR-042) shows that a review started, but not whether it finished, nor what it concluded: it left both out. The session logs record a turn's end, but a turn also ends when the agent asks a question or the developer stops it, and a log goes a week after its last event. Only the review knows it finished, and its verdict, *yes*, *yes-with-assumptions* or *no*, is what says whether the requirement is ready. Answering its questions means editing the requirement, so a verdict holds only for the text it was given.

## Decision

- **The review saves its result.** The repo template's `review-requirement` ends by passing its review to `save-review.sh`, beside it in its skill folder, which saves it as `<git common dir>/repocop/reviews/<requirement's file name>`: a header with the verdict, the count of blocking questions, the SHA-256 of the requirement's file as reviewed and when it was saved, then the review. On the developer's machine, out of every commit, replacing the requirement's last saved review. The skill stays read-only towards the repository: this is its one write.
- **RepoCop tells a requirement's standing from it**, read as it reads the history, with no git call: a review started after the last one saved is unfinished; with none saved and none started, it isn't reviewed; a file that differs from the one reviewed has changed since; else the verdict tells, as Not ready, Ready with assumptions or Ready. Board cards to do or in progress show it, and the requirement's page shows it with the review.
- **Ready is the review's verdict, not the developer's say.** There is no override: a developer who settles a blocking question edits the requirement, which a review then sees.

## Consequences

- A review that ran before the template's skill saved reviews, or that was stopped, shows as unfinished until a review saves its result.
- A review run in a worktree whose copy of the requirement differs from the primary checkout's shows as changed since review, as the board reads the checkout.
- Only the latest review of a requirement is kept. Each run still shows in its history.
- RepoCop names the template's review workflow, `review-requirement`, to tell a started review from other runs.
- Any local process can write a saved review: it is read only as a regular file in the folder, never through a link, and shown escaped.

## Alternatives rejected

- **Tell the standing from the history and git alone**, as a review run newer than the file's last change. It can't tell a finished review from a stopped one, nor a *no* from a *yes*.
- **Take a turn's end in the session's log as the review's end.** A turn also ends on a question or when stopped, and the log goes a week on.
- **A `reviewed:` field the developer sets in the requirement's front matter.** It would track progress in the requirement, which `.claude/rules/specs.md` and ADR-042 rule out.
- **Keep every saved review.** The history already keeps each run; the standing needs only the latest result.
- **Save it in the checkout's `.reviews/`**, as a branch review is. That folder is per worktree, so a review in one worktree wouldn't be seen from the primary checkout.
