# ADR-042: The repository's hook keeps every workflow run, in a history nothing removes

**Status:** accepted · **Date:** 2026-11-06

## Context

Before asking a session for a requirement's next step, the developer needs to know which steps it has had: whether it was reviewed, whether that review was addressed. The session logs record each workflow a session starts (ADR-040), but the hook removes a log a week after its last event, so a review done in a session closed eight days ago leaves no trace, and a requirement's work often runs longer than that.

## Decision

- **The hook appends each `workflow` line it writes to the session's log to `<git common dir>/repocop/history.jsonl` too:** the same line, in the same format, beside the session logs, out of every commit. Nothing removes it: not the hook's clean-up, and never RepoCop.
- **A requirement's page shows the runs on it** from that history and from the sessions' logs, every one whatever its age, each run once, so runs from before the hook kept a history show while their log is there. A run is on a requirement by the rule a session's workflow is.
- **RepoCop reads it as it reads the logs:** as a regular file inside the git folder, never through a link, read again only once it has changed, shown escaped.

## Consequences

- The history grows by one short line per workflow run, a few hundred bytes, for as long as the repository is used on the machine. Removing old runs is left out until it is needed.
- A run that names no requirement and started on a branch that belongs to none, as `/implement bulk-import` does on the default branch, is told its requirement by the branches its session went on to only while the session's log is there. Once the log is gone, it no longer shows.
- A repository keeps runs for good only once a template sync brings the new hook to the branch its sessions start on. Until then the page says its runs last only as long as their log.
- Any local process can write the history, as it can a log: what it says is shown escaped, and a line that can't be read is skipped.

## Alternatives rejected

- **Read the session logs only.** Runs would drop out a week after their session's last event, which is when the question of whether a review was done tends to come up.
- **Keep the logs longer, or for good.** A log holds every event of a session, hundreds of kilobytes for a long one, when the history needs one line per run.
- **Copy the runs into RepoCop's database as it reads the logs.** It would keep only what RepoCop saw while running, and hold state the repository's sessions own, which ADR-040 kept out of the database.
- **Record the runs in the repository, in commits or the requirement.** A requirement is the developer's statement of the work and isn't edited to track progress, and commits don't show a run that changed nothing, such as a review.
