---
depends-on:
  - fleet-dashboard
  - no-agent-runs
---
## Requirement

The developer runs the workflows in their own agent sessions, in a terminal, in VS Code or in Claude Code's agent view, and agents make their own worktrees and branches. RepoCop sees none of it: it can't say what is being worked on right now, or which session is waiting for the developer.

Each onboarded repository's agent sessions report what they do as they do it: a session starting, a workflow starting on a requirement, the session waiting for its user, a turn finishing, the session closing. They write it to a log on the developer's machine that RepoCop reads, so RepoCop shows the live state of the work however and wherever it was started, without launching anything.

## Acceptance Criteria

1. In a repository synced with the template, every Claude Code session that runs the repository's project hooks records each of these as it happens, wherever it runs (the primary checkout or any worktree, from a terminal, VS Code or agent view):
   - it started;
   - it moved to another folder;
   - a workflow (one of the repository's skills) started, whether the developer typed it or the agent chose it;
   - it is waiting for its user, either to allow a tool or to answer a question;
   - it went back to work after waiting;
   - its turn finished;
   - it closed.
2. Recording never delays or fails a session, and works whether RepoCop is running or not.
3. An event names the session, the time, the folder and branch the session is in at that moment, and the agent's process. Beyond those it holds only:
   - for a workflow: its name and the first line of its argument, cut at 200 characters;
   - for a permission wait: the tool's name;
   - for a close: the reason.

   Nothing else the session said or did.
4. The events stay on the developer's machine, out of every commit.
5. For each repository, RepoCop shows each session that has an event in the past day. For each it shows:
   - the requirement it works on: the one its latest workflow named, or else the one its branch belongs to (`.claude/rules/specs.md` › A branch's requirement), from the folder and branch of its latest event. A requirement's state is the requirement's, whatever branch the work is on;
   - the workflow it last started;
   - its state, and how long it has been in it. The states:
     - **Working**: its process is running, and it hasn't finished its turn or asked for anything.
     - **Needs input**: it is waiting for the developer, and shows what for: permission to use a tool, named, or an answer to its question.
     - **Waiting for instruction**: it finished its turn. This holds whether its process still runs or agent view has put it to sleep, which a reply wakes.
     - **Stopped mid-turn**: its process ended before the turn finished, as when it crashed, was killed, or the machine shut down.
     - **Closed**: the session ended, and how (it exited, was cleared, or was logged out).
6. A requirement's card on the fleet board, and its page, show its sessions. The sidebar lists the sessions that need input. A page showing sessions refreshes while any of them is working or needs input, as live views do.
7. A session that is working, needs input or is waiting for instruction puts its requirement In progress on the board, unless a later stage applies.
8. A session tied to no requirement still shows, under its repository, so no running work goes unseen.
9. When a repository's default branch on `origin`, as last fetched, lacks the recording hook, RepoCop says so: a template sync brings it, and sessions on branches made before that sync record nothing.
10. Showing sessions keeps every page fast. With 20 repositories and 50 sessions from the past day, it adds no noticeable delay to a page or its refreshes. Manual check: under 100 ms per page.

## Out of scope

- RepoCop sending instructions to a session. A later change covers it.
- Answering a session's permission prompts or questions from RepoCop.
- Agents other than Claude Code. The log's format is RepoCop's own, so another agent can write it later.
- What a session said, its transcript or its diff.
- Reading Claude Code's own session files or its `claude agents` listing.
- Sessions on other machines.

## Implementation Notes

- Verified on Claude Code 2.1.312, in one-shot and background sessions in a worktree:
  - A typed `/implement x` fires `UserPromptExpansion` with `command_name` and `command_args`.
  - A skill the agent chooses fires `PreToolUse` on `Skill`, with `tool_input.skill` and `tool_input.args`.
  - A permission prompt fires `PermissionRequest` at once, with the tool and its input, and `Notification` with `notification_type: permission_prompt` a few seconds later.
  - `Stop` carries `stop_hook_active`, and `SessionEnd` carries `reason`.
  - Project hooks fire in background sessions. Those need the workspace trusted, which is looked up by the primary checkout's path. One-shot sessions run hooks either way.
  - Project hooks fire in the VS Code extension: this repository's amend guard stopped a command in a VS Code session.
  - A command hook runs as `sh -c`, so the `claude` process is the hook shell's parent. Its process name is the version, such as `2.1.312`, not `claude`.
- Still to verify: which event a question the agent asks fires, either `Notification` with `elicitation_dialog`, or the asking tool's `PreToolUse` or `PermissionRequest`.
- The minimum Claude Code version is 2.1.312, where these were verified, unless an older one is shown to work. `make doctor`'s check rises to it.
- **The hook.** The template ships one plain-`sh` hook, managed. In its merged settings it is registered with `async: true` on:
  - `SessionStart` and `CwdChanged`;
  - `UserPromptExpansion`, and `PreToolUse` on `Skill`;
  - `PermissionRequest`, and `Notification` of types `permission_prompt` and `elicitation_dialog` only (`idle_prompt` isn't a wait);
  - `PostToolUse`, `Stop` and `SessionEnd`.

  It appends one line per event to `<git common dir>/repocop/sessions/<session id>.jsonl`. That folder is shared by every worktree of the repository and is never committed.
- **Picking the fields.** The hook picks out only the fields criterion 3 lists. It never copies the payload whole, since that would store the prompt, commands and the agent's last message. It decodes the JSON the way the amend guard does, needing only `sh` and `awk`, and is tested with recorded payloads under `mawk` and `gawk --posix`, as `backlog.sh` is.
- **A session's requirement.** A workflow's argument names its requirement's path, as `/implement specs/changes/todo/bulk-import.md` does, or a path into the repository's requirements folder anywhere in its first line, as `/address-review` with a requirement first does. A workflow run without one works on the branch's requirement (the skills default to it), so the branch decides. `specs/architecture.md` › Fleet board's In progress rule grows to count a live session.
- **The log format** is RepoCop's protocol, written into `specs/architecture.md`, and is agent-neutral, so RepoCop's reader needs no agent module. One JSON object per line:
  - Always: `v` (the format's version, 1), `at`, `session`, `event`, `cwd`, `branch`, `pid` and `pid_start`.
  - `event` is one of `started`, `moved`, `workflow`, `waiting`, `working`, `turn-finished` or `closed`.
  - Per event, as it applies: `workflow`, `argument`, `waiting_for` (`permission` or `answer`), `tool` and `reason`.
  - `PostToolUse` after a wait records `working`.
- **Process checks.** Whether a session's process is alive comes from its recorded process and start time in `/proc`, as restart recovery does. Elsewhere, Stopped mid-turn isn't detected, and a session shows its last state until a day passes without an event.
- **Reading the logs.** RepoCop reads only each log's last lines, skips malformed ones, caps what it reads, and containment-checks each log's path inside the repository's git common folder (`.claude/rules/safety.md` › Paths). Any local process can write a log, so pages render it escaped. The decision record says so.
- **Refreshing.** Only the sessions refresh, from their logs: the board's pull requests are read once per page load, never on a refresh, since each read is two GitHub calls per repository against an hourly limit.
- **Cost.** Each repository's git common folder is resolved once and kept in memory, since it doesn't change. Pages and refreshes then read the logs as files, without running git.
  - `.claude/rules/web-ui.md`'s "(from the database alone, never git)", and `specs/architecture.md` › The shell's "It reads only the database, so it adds no git call to a page", become a rule on cost.
  - That rule: the shell is on every page and refreshes every 2 s, so what it shows must cost each page little, whatever the number of repositories and sessions. Starting a process per repository on each page or refresh is what breaks it.
- **Specs.** `specs/architecture.md` gains a Session events section, with the format. A decision record covers RepoCop observing the developer's sessions through a log the repository's own hooks write, rather than launching them (ADR-037, ADR-001). `specs/product.md`'s Vision sentence about starting, watching and steering agents' work grows to cover sessions RepoCop didn't start.

## Open questions

1. **How long a session's log is kept.** **→** The hook deletes a session's log a week after its last event, when it next runs in that repository. RepoCop never deletes it.
2. **Where a session with no requirement shows.** **→** In its repository's row on the main page, as "other sessions".
