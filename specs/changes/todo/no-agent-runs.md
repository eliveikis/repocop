## Requirement

The developer runs the workflows in their own agent tool, such as Claude Code's agent view, a terminal or VS Code, where the agent has their sign-in, their permissions and the conversation so far. RepoCop's own way of running them goes unused: the Start button that runs Claude in a worktree RepoCop makes, and the Review and pull request buttons that act only on the branches those runs create. That path is most of RepoCop's code, ties it to one vendor's SDK, and gives a requirement two ways of being worked on that the board and the session events have to tell apart.

RepoCop stops running coding agents. It shows where every requirement stands, gives the line that runs each workflow in the developer's own agent, and keeps every repository in step with the repo template.

## Acceptance Criteria

1. A requirement's page offers no way to start a workflow, a review or a pull request action. For each of the repository's workflows, it still gives the line that runs it on the requirement in the developer's own agent, and names the branch to do the work on.
2. RepoCop launches no coding agent: no Claude Code session and no Codex review.
3. Template sync works as before: its plan, its commit on its own branch and worktree, pushing that branch and opening its pull request, and removing it.
4. The main page has no Claude sign-in panel, and `make doctor` checks only what RepoCop itself runs.
5. The board's In progress no longer counts a RepoCop task. The sidebar and the quick switcher list no active tasks, since there are none, and the switcher still finds repositories, requirements and template syncs.
6. A config file that still sets a setting only agent runs used is refused, naming the setting, as other retired settings are.
7. The product's vision and pillars, `CLAUDE.md`'s invariants, `specs/architecture.md`, and the safety and agents rules describe RepoCop as running no coding agents.

## Out of scope

- Session events and requests to sessions: `session-events` and `queue-next-step`.
- Reviewing or opening a pull request for the developer's own branches from RepoCop (open question 1).
- Anything the repo template ships to repositories, such as the workflow skills and `.reviews/review.sh`, which stays.
- Deleting the worktrees and branches past runs left. RepoCop never deletes them.

## Implementation Notes

- **What goes:**
  - `services/claude.py`, `services/codex.py`, `services/reviews.py`, and the runner's sessions and reviews;
  - the task page's transcript, instruction box and terminal-resume line;
  - the Claude sign-in panel;
  - the `claude-agent-sdk` dependency, and the fake Claude and Codex in `tests/fakes/`.
- **What stays:** a template sync stays a task, with its worktree, branch and pull request actions (`services/pull_requests.py`, `services/github.py`), and so does the `tasks` table that records it.
- **Settings:** the retired ones (`claude_bin`, `anthropic_api_key`, `review_model`, `review_effort`) join the config's list of retired keys.
- **Decision records:** one new record covers RepoCop running no coding agents. It supersedes, in whole or in part:
  - ADR-001 (the Agent SDK), ADR-003, ADR-008, ADR-009 and ADR-010 (sessions in worktrees, their permissions, waiting and recovery);
  - ADR-012 (a requirement's worktree), ADR-017 (one active task per worktree), ADR-018 and ADR-019 (sign-in and terminal resume);
  - ADR-025 (branch reviews);
  - ADR-023, for requirement branches only.

  ADR-024 (not tied to one agent) stands. ADR-026's `agent/` names stay for sync branches.
- **Rules and specs that shrink:**
  - `.claude/rules/safety.md` › Claude sessions, Reviews, and the parts of Pushing about requirement branches;
  - `.claude/rules/agents.md` and `tests/test_architecture.py`'s agent checks, together;
  - `.claude/rules/testing.md`'s fakes.

## Open questions

1. **Review and pull request buttons for requirements.** **→** Removed with the runs. Agent tools push and open their own pull requests, `.reviews/review.sh` runs the same Codex review by hand, and `queue-next-step` can ask a session to review or address a review. The alternative keeps them and points them at the requirement's branch wherever it lives, which changes the safety rules on what RepoCop pushes and where Codex may run.
2. **Past runs' records.** **→** A forward-only migration drops the tasks and events of past workflow runs and reviews, and their pages go. Their worktrees and branches stay on disk, untouched.
