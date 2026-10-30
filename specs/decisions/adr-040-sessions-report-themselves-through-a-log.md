# ADR-040: Sessions report themselves through a log the repository's hook writes

**Status:** accepted · **Date:** 2026-10-29

## Context

The developer runs the workflows in their own agent sessions, in a terminal, in VS Code or in Claude Code's agent view, and RepoCop launches none (ADR-039). Its board reads where each requirement stands from branches and pull requests (ADR-038), which show work only once it is committed or pushed. It couldn't say what is being worked on right now, or which session is waiting for the developer.

## Decision

- **Each session reports itself.** The repo template ships a hook, registered `async` on the session events RepoCop shows, which appends one line per event to `<git common dir>/repocop/sessions/<session id>.jsonl`. RepoCop reads those logs and launches nothing.
- **The log's format is RepoCop's own**, versioned and agent-neutral (`specs/architecture.md` › Session events): another agent's hook can write it, and RepoCop's reader needs no agent's module.
- **A line holds only what showing a session needs:** the session, the time, its folder, branch and process, and a workflow's name and the first line of its argument, the tool a permission wait is for, or why it closed. Never a prompt, a command or what the agent said.
- **The logs stay on the developer's machine**, in the git folder every worktree shares, out of every commit. The hook removes a log a week after its last event; RepoCop never deletes one.
- **Events are ordered by when their hook started.** Hooks run async and finish in any order, so each line carries the time its hook started, and RepoCop orders events by it, not by where they land in the log. Every tool use is recorded as working, so a wait that lands late can't outlast the work that followed it.
- **Reading is cheap and wary.** RepoCop asks git for each repository's git common folder once, then reads the logs as files: each from its end back to its latest workflow the first time, then only what is appended, only regular files inside the folder, skipping lines it can't read. Any local process can write a log, so what it says is shown escaped.
- **The shell refreshes the session lists every 2 s** on every page, in one request that starts no process and doesn't read GitHub. What the shell shows must cost each page little, rather than read only the database.

## Consequences

- A session shows however and wherever it was started, as long as it runs the repository's project hooks: a repository synced before the hook existed, or a branch made before the sync that brought it, records nothing, and the board says so for a default branch that lacks it.
- Background sessions run project hooks only in a workspace the developer trusted.
- Whether a session stopped mid-turn is told from `/proc`; elsewhere a session shows its last state until a day passes.
- The log is a protocol: a change to it bumps `v`, and the reader skips a line of a version it doesn't know.
- What a session reports is what Claude Code's hooks expose. A behaviour they don't show, such as agent view putting a session to sleep, is inferred: a finished turn whose process ended still waits for an instruction.

## Alternatives rejected

- **Read Claude Code's own session files, or its `claude agents` listing.** They are Claude Code's internals, unversioned, hold the whole conversation, and would tie RepoCop to one vendor.
- **Have the hook call RepoCop over HTTP.** A session would depend on RepoCop running, and on a port the hook would have to know; a file works whether RepoCop runs or not.
- **Keep the events in RepoCop's database.** RepoCop would have to be running to receive them, and the database would hold state the repository's sessions own.
- **Record the hook payload whole.** It carries the prompt, commands and the agent's last message, which RepoCop doesn't need and shouldn't keep.
