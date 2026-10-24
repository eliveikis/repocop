# ADR-022: The coordinator fetches in a primary checkout on request

**Status:** accepted · **Date:** 2026-10-01

## Context

The coordinator's pages show how far each primary checkout is ahead of and behind its upstream. Those counts are only as fresh as the checkout's last fetch. The primary checkout is human-owned, and until now the coordinator's only writes there were a saved requirement file and the template's missing files (ADR-004, ADR-011).

## Decision

- The repository's page has a Fetch button. It runs `git fetch origin` in the primary checkout, with no tags, no pruning and no submodule recursion, so only remote-tracking branches change.
- Nothing else fetches: no page load does, and nothing runs in the background.
- The coordinator never pulls, merges, rebases or checks out in a primary checkout.
- Reading a checkout's state takes no optional git locks, so showing it never rewrites the index.

## Consequences

- The working tree, index, HEAD, local branches and tags are the same after a fetch as before.
- The fetch runs inside the request, with the network timeout, as onboarding's clone does (ADR-015).
- Tags and pruned branches reach the checkout only when the human fetches in a terminal.
- When the last fetch happened is read from the modification time of the checkout's `FETCH_HEAD`, so nothing is stored.

## Alternatives rejected

- **No fetch at all**, showing the counts as of the human's own last fetch. It needs no new write in a human-owned checkout, but the counts stay stale until the human fetches in a terminal, which is the trip the page is meant to save.
- **Fetching on page load or on a schedule.** It puts a network call, with its credentials and timeouts, behind every page view, and changes a human-owned checkout without anyone asking.
