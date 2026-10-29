---
depends-on:
  - session-events
---
## Requirement

Once RepoCop shows a requirement's live sessions, the developer can see that one is ready for its next step: a requirement reviewed and ready to implement, or a review saved and ready to address. Moving it on still means finding that session in a terminal, VS Code or agent view and typing the next command.

From a requirement's page, the developer asks one of its sessions to run one of the repository's workflows on it. The request waits on the developer's machine until that session picks it up: when its current turn finishes if it's working, or at once if it is waiting for instruction. RepoCop doesn't launch or manage the session. The session works in whatever environment it was started in, and the developer sees the request arrive there.

## Acceptance Criteria

1. A requirement's page offers, for each of its live sessions, to run any of the repository's committed workflows on that requirement. Nothing sends a request but that click.
2. A request names only a workflow and the requirement. The developer can't add free text, and RepoCop refuses a workflow the repository hasn't committed.
3. A session that is **Working**, or **Needs input**, gets the request when its turn finishes, and carries straight on with it. A session **Waiting for instruction** whose turn finished less than an hour ago gets it at once, without anyone typing in it. The states are `session-events`'.
4. A request is delivered once, to the session it was meant for, and the page shows it as waiting, then delivered. Once the session starts the workflow, the page shows that as it shows any other (`session-events`). A request that was delivered, but whose workflow hasn't started within a few minutes, says so.
5. A request can be cancelled while it waits.
6. A session that can't be reached says why, and gives the line to run in it instead:
   - it finished its turn more than an hour ago;
   - it is **Stopped mid-turn** or **Closed**;
   - or in a repository whose template doesn't deliver requests yet.
7. One-shot sessions (`claude -p`) are never held up waiting for a request.

## Out of scope

- Starting a new session, or resuming a stopped one, from RepoCop.
- Answering a session's permission prompts or questions from RepoCop.
- Requests from anywhere but a requirement's page, or from another machine.
- Agents other than Claude Code.

## Implementation Notes

- Verified on Claude Code 2.1.312, in a background session in a worktree:
  - A `Stop` hook that returns `decision: block` with a reason makes the session carry on at once, with the reason as feedback.
  - An `asyncRewake` hook armed at `Stop`, which waited for a file and exited 2, woke the session, which had finished its turn, within a second. The session received the hook's stderr as a system note and invoked the skill it named, with its argument.
  - Worded as "run the `<workflow>` skill with the argument `<path>`", the session called the skill. Another wording was answered without the skill being called.
- In a one-shot session, an armed `asyncRewake` listener held up the turn's continuation for about 90 seconds. The hook must not arm one there: _TBD: how a hook tells a one-shot session from the rest._
- Requests wait as files in `<git common dir>/repocop/inbox/<session id>.json`, beside the session events. The template's hook (`session-events`) delivers them, deletes each once delivered, and records that as an event. It also checks the workflow is a committed skill in the session's checkout.
- An `asyncRewake` hook's timeout is enforced, and background sessions' processes stop after about an hour idle. The listener's timeout is therefore an hour, and a session whose turn finished longer ago is unreachable (criterion 6).
- `.claude/rules/safety.md` gains the rule that a request reaches a session only on an explicit click, as a workflow and a requirement, and nothing else. A decision record covers RepoCop moving a developer's own sessions on by request, rather than launching its own.

## Open questions

1. **Which session gets the request when a requirement has several.** **→** The developer picks one. Each live session has its own button.
2. **How long a waiting request lasts.** **→** Until it's delivered or cancelled, or its session ends. A session's end removes the request.
