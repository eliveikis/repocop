---
depends-on:
  - codex-workflows
---
## Requirement

The goal is that developers of RepoCop, and of every repository it keeps in step with the template, can use the same workflows and the same context management in Codex as in Claude Code, so they aren't limited to a single service. This change does that for what RepoCop shows and steers. A Codex session reports itself in the session log as a Claude Code session does, so RepoCop shows it wherever it shows sessions and adds its workflows to their requirement's history, and a request from a requirement's page reaches a Codex session as it reaches a Claude Code one. Today only Claude Code's hook writes the log, and a request reaches a session only through Claude Code's hook and inbox socket.

## Acceptance Criteria

1. The template's session hook runs in Codex sessions too, in RepoCop and in every synced repository, and writes the same log in RepoCop's format, each line naming its agent. A Codex session records each event of the format that Codex tells its hooks of. `specs/sessions.md` says how Codex's events map to them, and which it can't record.
2. A Codex session shows wherever a Claude Code session does: on its requirement's page, on its repository's page and, while it needs input, in the sidebar, in the same states, with its branch, its workflow and its agent. The workflows it runs join their requirement's history.
3. A request for a Codex session that is working, or needs input, waits in the inbox, is taken by the session's own hook when its turn ends, with the same checks, and the session then runs the workflow.
4. A request for a Codex session that has completed its turn reaches it at once, if Codex offers a way that `.claude/rules/safety.md` › Requests to sessions allows. If it offers none, the page says the request waits for the session's next turn, and gives the line to run in it.
5. A session that can't be reached gives the line to run in its own agent.

## Out of scope

- RepoCop running `codex queue` or any other Codex command: it runs only git and the GitHub CLI (ADR-039).
- Codex Cloud tasks and `codex exec` runs.
- Agents other than Claude Code and Codex.

## Implementation Notes

- Codex 0.166 mentions the hook events `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop` and `SessionEnd`, and nothing like Claude Code's `CwdChanged`, `Notification` or `UserPromptExpansion`. The mapping, and whether Codex's `Stop` can carry a session on as Claude Code's `decision: block` does, are checked against the installed Codex CLI first, and recorded with its version in `specs/sessions.md`, as Claude Code's are. If `Stop` can't, criterion 3 can't hold: raise it before building the rest.
- Without `UserPromptExpansion`, the hook can find a workflow in a prompt that starts with one of the repository's skills, and record only the skill and its argument, as the format allows: never the prompt.
- `session-events.sh` stays the format's one writer: Codex registers the same script, which is told which agent runs it. A line without an agent is Claude Code's, so logs written before this change read as they did.
- Codex runs a local app-server daemon and has `codex queue`. Whether a socket of Codex's meets the safety rule, and what message starts a turn there, is checked. A mechanism other than ADR-041's gets its own decision record.
- The hook's folder and the socket's message are among the places `.claude/rules/agents.md` lists. This change adds Codex's beside them, and changes that rule and `tests/test_architecture.py` together.
- These follow:
  - `specs/sessions.md` (The session log, What a session shows, Session requests);
  - `specs/requirements.md` (A requirement's history), where it names one agent;
  - `.claude/rules/safety.md` (Requests to sessions);
  - `specs/architecture.md` (Coding agents).
