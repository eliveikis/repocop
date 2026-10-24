# Untrusted repositories

## Problem

Claude Code applies a repository's `permissions.allow` rules only once someone has accepted its trust prompt, and it looks trust up by the primary checkout's path, even from a worktree (`specs/architecture.md` › Claude Code integration). The coordinator clones repositories during onboarding, so a repository can reach its first task without anyone ever having opened Claude Code in it. Every allowlisted command in its sessions is then refused: the skills can't run `git commit` or the check command. The only sign is a warning on the session's stderr, which the coordinator discards. So the task stalls on denials that look like an allowlist mistake, and nothing tells the human what's actually wrong or how to fix it.

## Goal

A session never runs with its repository's allowlist silently ignored. When Claude Code doesn't trust a repository, its task stops before Claude does anything, and the human is told why and how to fix it. The fix stays the human's own decision, made through Claude Code.

## Depends on

req-1 (v0.1): `services/claude.py`, the task runner, and the setup page.

## Requirements

### 1. Detect it at launch

`services/claude.py` reads each session's stderr. When Claude Code reports that it ignored the repository's allow rules because the workspace isn't trusted, the session is stopped before its first turn runs anything (to verify: that the warning arrives before the first tool call). The task becomes `failed`, with a reason that names the primary checkout and the fix: open Claude Code in that folder once, accept its trust prompt, then start the task again. Stderr lines about anything else don't stop a session.

### 2. Say it up front

Setting up a repository ends with the same instruction: before its first task, open Claude Code once in the primary checkout and accept its trust prompt.

### 3. Never bypass trust

Trust is the human's decision, made through Claude Code. The coordinator never writes Claude Code's own configuration (`~/.claude.json`, `~/.claude/`), and never passes a repository's allow rules as CLI-level settings, which would skip the trust check. A failed task is started again once the human has trusted the repository; nothing retries on its own.

### 4. Verified, then faked

Before building on it, check with the real CLI (one short run on the subscription, with the user's go-ahead):

- The exact warning, and when it arrives relative to the `init` message and the first tool call.
- That once the primary checkout is trusted, a session in one of its worktrees applies the allowlist.
- What else Claude Code ignores in an untrusted workspace, such as `env` settings, hooks and MCP servers, and whether deny rules and `ask` rules still apply.

Record the facts in the "Verified against the real CLI" list in `specs/architecture.md` › Claude Code integration. The fake then reports the warning through the same stderr callback, at the same point (`.claude/rules/testing.md`).

## Acceptance Criteria

- The real CLI's behaviour in an untrusted workspace is verified and recorded in `specs/architecture.md`, and the fake follows it.
- A session whose repository isn't trusted is stopped before it runs anything, and its task fails with a reason naming the primary checkout and the fix.
- A session in a trusted repository runs as before, and unrelated stderr output doesn't stop it.
- The setup page tells the human to open Claude Code once in the primary checkout and accept its trust prompt.
- The coordinator never writes Claude Code's configuration and never passes a repository's allow rules as CLI-level settings.
- A task that failed this way runs normally when started again after the repository is trusted.

## Scope boundaries

Not part of this change:

- Trusting repositories automatically, or on the human's behalf.
- Showing trust state on repository pages before a task has run.
- Interactive sessions, where Claude Code asks for trust itself.

## Open questions

Proposed defaults are marked **→**.

1. **How to detect it.** **→** Match Claude Code's stderr warning, pinned by a test against the verified wording, so a change in wording fails loudly in req-3's smoke test rather than silently. The alternative, reading trust flags from `~/.claude.json` before launch, depends on another tool's internal file.
2. **A repository with no allow rules.** Claude Code then has nothing to ignore and may print no warning. **→** Nothing to detect: its sessions lose nothing by being untrusted, so they run as usual. To verify: whether a warning appears anyway.
