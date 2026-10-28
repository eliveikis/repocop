---
depends-on:
  - fleet-dashboard
---
## Requirement

The developer runs the workflows in their own agent sessions, in a terminal, in VS Code or in Claude Code's agent view, and agents make their own worktrees and branches. RepoCop sees none of it: it can't say what is being worked on right now, or which session is waiting for the developer, because it only knows the sessions it started itself.

Each onboarded repository's agent sessions report what they do as they do it: a session starting, a workflow starting on a requirement, the session waiting for its user, a turn ending, the session ending. They write it to a log on the developer's machine that RepoCop reads, so RepoCop shows the live state of the work however and wherever it was started, without launching anything.

## Acceptance Criteria

1. In a repository synced with the template, every Claude Code session in it records each of these as it happens, wherever it runs (the primary checkout or any worktree, from a terminal, VS Code or agent view):
   - it started;
   - a workflow (one of the repository's skills) started, with its argument, whether the developer typed it or the agent chose it;
   - it is waiting for its user: a permission prompt or a question;
   - its turn ended;
   - it ended.
2. Recording never delays or fails a session, and works whether RepoCop is running or not.
3. An event names the session, the time, the folder and branch the session is in, and the agent's process. It holds nothing else the session said or did.
4. The events stay on the developer's machine, out of every commit.
5. For each repository, RepoCop shows each session that has an event in the past day: the requirement its branch belongs to (`.claude/rules/specs.md` › A branch's requirement), the workflow it last started, whether it is working, waiting for its user, idle after a turn, or ended, and how long ago. A session whose process is gone without an ended event shows as ended.
6. A requirement's card on the fleet board, and its page, show its live sessions. The sidebar lists the sessions waiting for their user beside RepoCop's own active tasks.
7. A session on a branch that belongs to no requirement still shows, under its repository, so no running work goes unseen.
8. A repository that doesn't record sessions yet says so, and that a template sync brings it.

## Out of scope

- RepoCop sending instructions to a session. A later change covers it.
- Agents other than Claude Code. The log's format is RepoCop's own, so another agent can write it later.
- What a session said, its transcript or its diff.
- Reading Claude Code's own session files or its `claude agents` listing.
- Sessions on other machines.
- Retiring RepoCop's own task runner.

## Implementation Notes

- Verified on Claude Code 2.1.312, in one-shot and background sessions in a worktree:
  - A typed `/implement x` fires `UserPromptExpansion` with `command_name` and `command_args`.
  - A skill the agent chooses fires `PreToolUse` on `Skill`, with `tool_input.skill` and `tool_input.args`.
  - A permission prompt fires `PermissionRequest` at once, with the tool and its input, and `Notification` with `notification_type: permission_prompt` a few seconds later.
  - `Stop` carries `stop_hook_active`, and `SessionEnd` carries `reason`.
  - Project hooks fire in background sessions. Those need the workspace trusted, which is looked up by the primary checkout's path. One-shot sessions run hooks either way.
  - A command hook runs as `sh -c`, so the `claude` process is the hook shell's parent. Its process name is the version, such as `2.1.312`, not `claude`.
- Still to verify: `Notification` for a question the agent asks.
- The template ships one plain-`sh` hook, managed, registered with `async: true` on those events in its merged settings. It appends one JSON line per event to `<git common dir>/repocop/sessions/<session id>.jsonl`. That folder is shared by every worktree of the repository and is never committed.
- The log's format is agent-neutral, so RepoCop's reader needs no agent module. Only the hook is Claude Code's.
- Liveness comes from the recorded process and its start time in `/proc`, as restart recovery does. Elsewhere, a session counts as ended after a day without events.
- Any event after a wait, including a tool finishing, means the session is working again. The hook therefore also records `PostToolUse`, with no detail.
- `specs/architecture.md` gains a section on session events. A decision record covers RepoCop observing the developer's sessions through a log the repository's own hooks write, rather than launching them (ADR-037, ADR-001).

## Open questions

1. **How long a session's log is kept.** **→** The hook deletes a session's log a week after its last event, when it next runs in that repository. RepoCop never deletes it.
2. **Where a session with no requirement shows.** **→** In its repository's row on the main page, as "other sessions".
