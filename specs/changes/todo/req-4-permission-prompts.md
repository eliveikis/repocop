# Permission prompts on the task page

## Problem

Coordinator sessions run headless with `acceptEdits` plus the repository's `.claude/settings.json` allowlist, and never bypass permissions (ADR-008). When Claude wants a tool call those settings don't allow, there's nobody to ask, so Claude Code refuses it and tells Claude so. The same happens to every `ask` rule: in the default template, `git push` means "never" in a coordinator session rather than "ask me".

At the terminal the user approves such prompts often: a one-off `ls`, `mkdir`, or `uv run pytest tests/x.py`. On the coordinator the task page can't grant anything. An instruction can only tell Claude to try something else, and widening the committed allowlist is the only lasting fix. So tasks stall, work around the refusal, or end their turn asking for a permission the user can't give. That breaks pillar 1: intervening in a running session should be cheap and normal.

## Goal

When a session wants a tool call its settings don't already allow, it asks on the task page instead of being refused. The user allows or denies that call, and the answer reaches exactly that request.

## Depends on

req-1 (v0.1): the task runner, the status machine, and the live task page.

## Requirements

### 1. Ask instead of refusing

Sessions register the Agent SDK's permission callback (`can_use_tool`). Claude Code calls it only for tool calls that the settings neither allow nor deny, and for `ask` rules. Everything the settings already allow, and file edits under `acceptEdits`, still run without asking. Deny rules still deny without asking. Permissions are never bypassed (ADR-008 still holds).

### 2. A status for "waiting on your answer"

While at least one request is pending, the task is `waiting_for_permission` (see open question 1). It's an active status, so the one-active-task-per-worktree rule and cancel apply. Answering the last pending request moves the task back to `running`. Task lists show the status like any other, so the user can see which tasks need them.

### 3. What the page shows

Each pending request appears in the task page header with:

- Claude Code's own prompt text (`title`, `description`, `decision_reason`) when it sends one; otherwise the tool name.
- The tool's input: the command for `Bash`, the path for file tools, and escaped, clipped JSON for anything else.
- Which subagent asked, when a subagent asked.

### 4. Answers

For each request the user can:

- **Allow once.** The tool runs with its input unchanged.
- **Allow for this session.** This is offered only when Claude Code suggests a rule. The rule applies to this session only, and no settings file is written.
- **Deny**, with an optional message. Claude receives the denial and the message, like the terminal's "No, and tell Claude what to do differently".

While a request is pending, the instruction box is replaced by the deny message: redirecting Claude means denying with a message. **Cancel** still works; it denies all pending requests and ends the turn.

### 5. Exactly one request

Each request is keyed by its task and Claude Code's tool-use id. An answer is accepted only for a request of that task that is still pending. A second answer to the same request, an answer to a request that has already ended, or an answer naming another task's request is refused with a visible reason and changes nothing. Answers are never broadcast, and nothing is allowed automatically or on a timeout.

### 6. A record in the transcript

Every request and its answer are recorded as task events: what was asked, the decision, and the message. The transcript shows both. Only execution state is stored (invariant 4).

### 7. Restarts

Pending requests end with the process. On startup, a `waiting_for_permission` task is recovered exactly like a `running` one (ADR-010): its leftover process is stopped, the note records where it stopped and which request was pending, and it becomes `waiting_for_user` if its session can be resumed. On resume, Claude retries and asks again if it still needs to.

### 8. Verified, then faked

Before building on it, check with the real CLI (one short run on the subscription, with the user's go-ahead):

- A tool call outside the allowlist reaches the callback, and so does an `ask` rule.
- Where the callback falls relative to the `AssistantMessage` carrying the `tool_use` block.
- What arrives after an allow and after a deny.
- What happens with parallel tool calls.

Record the facts in the "Verified against the real CLI" list in `specs/architecture.md` › Claude Code integration. The fake then raises permission requests through the same callback, in that order (`.claude/rules/testing.md`).

## Acceptance Criteria

- The real CLI's behaviour around a permission request is verified and recorded in `specs/architecture.md`, and the fake follows it.
- A tool call the worktree's settings don't allow, or an `ask` rule, moves the task to `waiting_for_permission` instead of being refused.
- Tool calls the settings allow, and edits under `acceptEdits`, don't ask. Deny rules still deny. Permissions are never bypassed.
- The task page shows each pending request with Claude Code's prompt text (or the tool name) and the tool's escaped, clipped input.
- Allowing once runs the tool, and the task returns to `running` once nothing is pending.
- Allowing for this session is offered only when Claude Code suggests a rule, and writes no settings file.
- Denying with a message delivers the denial and the message to Claude.
- An answer to a request that is no longer pending, or that belongs to another task, is refused with a reason and changes nothing.
- While a request is pending, instructions are refused with a reason, and cancel denies the pending requests and ends the turn.
- Requests and answers appear in the transcript.
- After a restart, a task that was waiting on a request is recovered like a running one, and its note names the request.
- Task lists show tasks that are waiting on a permission.

## Scope boundaries

Not part of this change:

- Writing permission rules to settings files from the UI. Lasting rules stay a human edit to the repository's committed `.claude/settings.json`.
- Notifications outside the coordinator (desktop, email, phone).
- Automatic approval, approval policies, or timeouts that allow.
- `auto` or `bypassPermissions` modes.
- Changing the default template's allowlist.

## Open questions

Proposed defaults are marked **→**.

1. **Status.** **→** A new active status, `waiting_for_permission`, so lists show which tasks are blocked on the user. The alternative is to keep `running` and show the request only on the task page, which is simpler but hides blocked tasks in lists.
2. **Timeout.** **→** None: a request waits until it's answered or the task is cancelled, like `waiting_for_user`. To verify: that neither the CLI nor the SDK times out a pending permission request on its own.
3. **`AskUserQuestion`.** Claude Code's multiple-choice question tool may reach the same callback once it's registered (to verify). **→** Deny it with a message asking Claude to put the question in its reply. The turn then ends and the user answers through the instruction box. A proper question form can be a later change.
4. **Parallel requests.** **→** List every pending request and let each be answered on its own. The task stays `waiting_for_permission` until none is pending.
