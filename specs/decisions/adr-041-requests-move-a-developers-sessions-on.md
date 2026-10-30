# ADR-041: A click moves a developer's own session on, through its hook or its socket

**Status:** accepted · **Date:** 2026-10-30

## Context

RepoCop shows each requirement's live sessions as they report themselves (ADR-040), so the developer can see when one is ready for its next step, but moving it on still meant finding that session in a terminal, VS Code or agent view and typing the next command. RepoCop runs no coding agent (ADR-039), so it can't start the step itself.

Claude Code offers two ways in. A `Stop` hook that returns `decision: block` with a reason carries the session on at once with that reason as its next instruction. And every session binds an inbox socket, whose path its hooks are given, where a message with priority `later` starts the session's next turn, or waits for the end of the one under way. An `asyncRewake` hook armed at `Stop` could also wake an idle session, but it holds a `claude -p` session up, how a hook tells such a session apart is undocumented, and its timeout caps how long a session stays reachable.

## Decision

- **From a requirement's page, on a click, the developer asks one of its live sessions to run one of the repository's committed workflows on it.** A request names only the workflow and the requirement's path, and is told to the session in one fixed wording that makes it call the skill.
- **A session at work gets it when its turn ends.** The request waits as a file in `<git common dir>/repocop/inbox/`, where it can be cancelled, until the session's own hook takes it at `Stop`, once, by renaming it, checks it, and returns Stop's decision to carry on.
- **A session waiting for an instruction gets it at once, through its socket**, which its log names, sent only when the socket is this user's, named after the session's process, in a folder no one else can write, and always with the session's id.
- **RepoCop writes the request into the checkout's git folder.** This is its one write in a human-owned checkout besides a fetch: made only on the developer's click, holding only a workflow and a requirement, beside the session logs, out of every commit.

## Consequences

- RepoCop still launches and manages nothing. The session works where it was started, and the developer sees the request arrive there.
- A session is reachable as long as its process runs: there is no limit on how long it has waited. One whose process ended, closed, stopped mid-turn, or whose hook predates requests, says why on the page and gives the line to run in it instead.
- RepoCop speaks Claude Code's socket message, which `.claude/rules/agents.md` lists among the few places that name one agent's own.
- A request is delivered once, and the page shows it waiting, delivered, and late when its workflow hasn't started within a few minutes.

## Alternatives rejected

- **An `asyncRewake` listener armed at `Stop`.** It holds a one-shot session up for as long as it waits, needs an undocumented way to tell such a session apart, and leaves a session unreachable once its timeout passes.
- **RepoCop sends every request through the socket at once, with priority `later`.** A request at work would wait in the session's own queue, where it can't be cancelled or shown as waiting.
- **A free-text instruction.** It would let a click on a page say anything to an agent with the developer's permissions.
- **Starting or resuming a session from RepoCop.** It is what ADR-039 retired: the developer's own tool runs and steers sessions.
