# ADR-025: Branch reviews by an agent's own review, Codex first

**Status:** accepted · **Date:** 2026-10-12

## Context

Before this, the only review the coordinator could ask for was Copilot's, which needs the branch pushed and a pull request open. A review was wanted earlier: before anything leaves the machine, and from another vendor than the one whose agent wrote the code.

Every coding agent now ships a review command of its own, and its vendor keeps improving it.

## Decision

- A review of a requirement's branch is an agent's own built-in review. The coordinator starts it and shows what it says, and adds no review logic of its own.
- Codex is the first reviewer: `codex review --base=origin/<default branch>`, behind `services/codex.py`, the only module that runs it. `codex` is found on `PATH` and uses the login `codex login` stored. The coordinator holds no credential for it.
- A review is a task of the coordinator's own in the requirement's worktree. It starts only on a click, it is advisory, and it never blocks a pull request. Asking Copilot for a review stays.
- A review changes nothing. Codex's read-only sandbox is asked for by name on every run, and the coordinator fails a review that left the worktree changed.
- A repository says what a review checks and skips in `REVIEW.md`. `AGENTS.md`, which Codex reads, points at the repository's instructions and at `REVIEW.md`. The repo template ships both as starter files.

## Consequences

- What a review says, how deep it goes and how it is laid out are Codex's. The coordinator shows the text as written, and doesn't count findings or read severities from it.
- Codex is optional. Without it, or signed out, only the Review action is refused.
- The branch's code goes to OpenAI, under the host's Codex login.
- Acting on a review takes a click: the Address review action starts the repository's `address-review` skill with the review's text. Nothing passes a review on by itself.
- A second agent has a module, and `.claude/rules/agents.md` holds it to the same boundary as the first.
- Tests run a fake `codex` from `PATH`, so the default suite never reaches Codex.

## Alternatives rejected

- **A reviewer of our own**, shipped to every repository through the template: prompts for a reviewer and a verifier, a finding format and a report file, run with opencode. We would own its prompts, its permissions and the quirks of the tool running it, and get none of a vendor's improvements.
- **opencode's built-in review.** It is one pass with nothing that confines it to read-only.
- **Blocking a pull request on a review.** It takes a decision the human keeps.
