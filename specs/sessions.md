# Sessions

RepoCop shows the developer's agent sessions as they work, however and wherever they were started, without launching anything: each session reports itself, in a log its repository's hook writes. From a requirement's page, the developer also asks one of its live sessions to run the next workflow on it, which moves the work on without finding the session in a terminal, VS Code or agent view.

## The session log

The repo template's hook, `.claude/hooks/session-events.sh`, runs in every Claude Code session that runs the repository's project hooks, in the primary checkout or any worktree, from a terminal, VS Code or agent view. It never delays or fails a session, and sessions on a branch made before a sync brought it record nothing. It appends one line per event to `<git common dir>/repocop/sessions/<session id>.jsonl`: a folder every worktree of the repository shares, on the developer's machine, out of every commit. When a session starts, it removes the logs that have gone a week without an event; RepoCop never deletes one. Each `workflow` line it also appends, the same line, to `<git common dir>/repocop/history.jsonl`, the repository's history of workflow runs, which nothing removes ([requirements.md › A requirement's history](requirements.md#a-requirements-history)).

**The format** is RepoCop's own, so another agent's hook can write it. One JSON object per line:

| Field | Holds |
|-------|-------|
| `v` | the format's version, `1` |
| `at` | when its hook started, in UTC, to the nanosecond where the host's `date` says: `2026-10-29T16:50:01.123456789Z`. Hooks finish in any order, so this, not a line's place in the log, orders events |
| `session` | the session's id, also the log's name |
| `event` | `started`, `moved`, `workflow`, `waiting`, `working`, `turn-finished` or `closed` |
| `cwd`, `branch` | the folder the session is in, and its branch there (`null` off a branch) |
| `pid`, `pid_start` | the agent's process and its start time as `/proc` shows it (`null` where there is none) |
| `socket` | the inbox socket where the agent takes messages, as Claude Code tells its hooks (`null` where it tells none) |
| `workflow`, `argument` | for `workflow`: the skill, and the first line of its argument, at most 200 characters |
| `waiting_for`, `tool` | for `waiting`: `permission` or `answer`, and the tool a permission is for when known |
| `reason` | for `closed`: why, as the agent says (`exit`, `clear`, `logout`, …) |

Nothing else the session said or did is recorded: never a prompt, a command or what the agent said. Claude Code's events map to them as follows:

| Event | From |
|-------|------|
| `started` | `SessionStart`, but for a compaction, which carries on the same session |
| `moved` | `CwdChanged` |
| `workflow` | `UserPromptExpansion` of one of the repository's skills, or `PreToolUse` on `Skill` naming one: typed or chosen by the agent |
| `waiting` | `PermissionRequest`, a `Notification` of a permission prompt or a question, and `PreToolUse` on `AskUserQuestion` |
| `working` | `UserPromptSubmit`, and every `PostToolUse` |
| `turn-finished` | `Stop` |
| `closed` | `SessionEnd` |

These were verified on Claude Code 2.1.312, the oldest version the hook supports. Background sessions run project hooks only in a workspace the developer trusted, which Claude Code looks up by the primary checkout's path.

Any local process can write a log, so RepoCop reads one only as the safety rule says (`.claude/rules/safety.md` › Paths), skips a line it can't read, and shows what it says escaped.

## What a session shows

A session shows while it has an event in the past day. Its state comes from its events, and from whether its process still runs:

| State | When |
|-------|------|
| Working | its last event put it to work, and its process runs |
| Needs input | it waits for permission to use a tool, named when known, or for an answer to its question, and its process runs |
| Completed | it started, or finished its turn, and waits for what the developer says next, whether its process still runs or agent view has put it to sleep, which a reply wakes. When its process isn't running, it says it is asleep or ended |
| Stopped mid-turn | its process ended while it was working or needed input: it crashed, was killed, or the machine shut down |
| Closed | it ended: it exited, was cleared, or was logged out |

- **What each shows:** how long it has been in its state, the workflow it last started, and its branch.
- **Its requirement** is the one in the requirements folder, or its archive, whose path in that folder its latest workflow's argument holds, as `/implement specs/changes/todo/bulk-import.md` does, the longest if several and whatever its file is called, or else the one its latest event's branch belongs to (`.claude/rules/specs.md` › A branch's requirement), from the requirements folder or its archive.
- **Its workflow** shows only while it is for that requirement: one whose argument named none was for the requirement of the first branch the session was on from its start that belongs to one, as `/implement` starts on the default branch and then makes its own, so a session that has moved on to another requirement shows no workflow until it starts one.
- **Where it shows.** A requirement's page shows its sessions, a repository's page all of its own, and the sidebar those that need input, in every repository. The lists refresh on their own ([ui.md › Staying current](ui.md#staying-current)).
- **Only where `/proc` is.** Whether a process runs is read from `/proc`, so elsewhere Stopped mid-turn isn't told, and a session shows its last state until a day passes without an event.

## Session requests

From a requirement's page, the developer asks one of its live sessions to run one of the repository's committed workflows on it. RepoCop doesn't launch or manage the session: the request reaches it where it runs, and the developer sees it arrive there.

- **Only a click, only a workflow and a requirement.** Each live session of the requirement has its own form, a choice among the skills committed in the repository and a button: no free text. RepoCop refuses a workflow the repository hasn't committed, and a requirement path that would change the request's meaning (a backtick, a backslash, a line break, an absolute path). The session is told: ``The developer asks, from RepoCop: run the `<workflow>` skill with the argument `<path>`.``, a wording verified to make Claude Code call the skill.
- **A session at work gets it when its turn ends.** For a session that is working, or needs input, the request waits as `<git common dir>/repocop/inbox/<session id>.json`, a JSON object of `v` (1), `id`, `workflow`, `requirement` and `at`, written as UTF-8, escaping only what JSON must. Until then it can be cancelled, and only one waits for a session at a time. When its turn ends, the session's own hook, `session-events.sh deliver`, registered on `Stop` and waited for, takes it by renaming it, so it is delivered once. It checks the workflow is a skill committed in the session's checkout and the requirement, its JSON decoded, a file there, or in the archive beside its folder when it was archived meanwhile, as completing a change does, that is no link and in no folder leading out of the checkout, and returns Stop's decision to carry on, with the wording above as its reason. A session's end removes the request still waiting for it.
- **A session that has completed its turn gets it at once**, through the inbox socket its log names: one line, `{"type":"user","session_id":…,"priority":"later","from":"RepoCop","uuid":…,"message":{"role":"user","content":…}}`, which starts its next turn, or waits for the end of one begun meanwhile. A message whose `session_id` isn't the session's is dropped by Claude Code, so it reaches no other. The socket is used only as `.claude/rules/safety.md` › Requests to sessions says. A request left just as the session's turn ended, which its hook may have looked for already, is handed over the same way, unless the hook took it first, which counts as sent, and one still waiting once the session is idle can be sent from the page.
- **A waiting request is checked again.** Any local process can write one, so one RepoCop takes is checked again, against the requirement it was asked for and the committed workflows, and dropped when it fails; one that never reached the session, as when its socket is gone, waits again. A request file is read only as a regular file, never through a link and without waiting on a pipe.
- **Delivered.** Whoever hands a request over records it in `<session id>.delivered.json` beside it, with when: written whole, then renamed into place, never written through a link there. The requirement's page shows a waiting request, then the delivered one, until the session starts its workflow, and says so when that hasn't happened within a few minutes.
- **The page stays current.** A requirement's page keeps what it offers each session up to date as the session's state, branch and workflow change, without losing a workflow being picked.
- **A session that can't be reached says why, and gives the line to run in it instead:** it closed, or stopped mid-turn; it has completed its turn but its process isn't running, as when agent view has put it to sleep; or its log names no socket, because the hook that recorded it predates requests, so a template sync brings them.

These rest on Claude Code 2.1.312: `Stop`'s `decision: block` carrying the session on at once, and a `later` message on a session's socket starting its next turn, in which it calls the skill named.
