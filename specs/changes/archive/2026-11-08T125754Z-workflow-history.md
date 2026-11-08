---
depends-on:
  - session-events
  - queue-next-step
---
## Requirement

Before asking a session for the next step on a requirement, the developer needs to know which steps it has had: whether its requirement was reviewed, its branch reviewed, that review addressed. Today a requirement's page shows only its sessions from the past day and the workflow each last started, and the session logs behind them are removed a week after their last event, so an earlier step leaves no trace.

A requirement's page shows its history: every workflow run on it, newest first, however long ago and whether or not its session is still there. The repository's own hook keeps the record, on the developer's machine, as it keeps the session logs.

## Acceptance Criteria

1. A requirement's page lists the workflows run on it, newest first: each with the workflow, when it started, its branch, and the session it ran in.
2. A run counts for the requirement a session working on it would: its argument holds the requirement's path, or else it was for the requirement of the first branch its session was on from its start that belongs to one (`session-events`, and a workflow shows only while its session works on what it was for).
3. A run stays in the history after its session closes, and after its session's log is removed: the template's hook keeps a record of every workflow run, which nothing removes.
4. Runs recorded before the hook kept that record show while their session's log is there, each once.
5. The history shows only what a session log line may hold (`session-events`), escaped. An empty history says that runs show once a session starts a workflow on the requirement. While the repository's default branch has a hook that doesn't keep the record yet, the history says its runs last only as long as their session's log, and that a template sync brings the hook that keeps them.
6. Showing the history costs a page load little, with one git call at most, which reads the hook on the default branch, and no GitHub read. The 2 s session refresh doesn't show it.

## Out of scope

- Telling which runs were asked for from RepoCop.
- Whether a run finished, and what it produced.
- Removing old runs from the record.

## Implementation Notes

- The hook appends each `workflow` line it writes to the session's log to `<git common dir>/repocop/history.jsonl` too, the same line, in the same format. Its week-old clean-up doesn't reach it.
- A run without a requirement path that started on a branch belonging to none, as `/implement bulk-import` does on the default branch, is told its requirement by the branches its session went on to, read from the session's log while it is there.
