## Requirement

The developer runs the workflows in their own agent tool, such as Claude Code's agent view, a terminal or VS Code, where the agent has their sign-in, their permissions and the conversation so far. RepoCop's own way of running them goes unused: the Start button that runs Claude in a worktree RepoCop makes, and the Review and pull request buttons that act only on the branches those runs create. That path is most of RepoCop's code, ties it to one vendor's SDK, and gives a requirement two ways of being worked on that the board and the session events have to tell apart.

RepoCop stops running coding agents. It shows where every requirement stands, gives the line that runs each workflow in the developer's own agent, and keeps every repository in step with the repo template. What the runs needed goes with them, so nothing is left that no longer does anything.

## Acceptance Criteria

1. A requirement's page offers no way to start a workflow, a review or a pull request action.
2. For each of the repository's workflows, a requirement's page still gives the line that runs it on the requirement in the developer's own agent, such as `/implement specs/changes/todo/bulk-import.md`, and names the branch to do the work on. Each line has a Copy button that puts it on the clipboard. Without JavaScript, the line shows as now, to select and copy by hand.
3. RepoCop launches no coding agent: no Claude Code session and no Codex review.
4. Template sync works as before: its plan, its commit on its own branch and worktree, and its page. That page lists what the sync wrote, shows its diff, pushes its branch and opens its pull request, and removes it.
5. When RepoCop stops while a sync is being committed, its next start marks that sync failed, so it can be run again, rather than leaving it running for ever.
6. The main page has no Claude sign-in panel, and `make doctor` checks only what RepoCop itself runs.
7. The board's In progress no longer counts a RepoCop task, and the sidebar has no active tasks section. The quick switcher still finds repositories, requirements and template syncs.
8. A config file that still sets a setting only agent runs used is refused, naming the setting, as other retired settings are.
9. Upgrading clears everything only agent runs used: past workflow runs and reviews and their pages, RepoCop's record of the requirements it ran work on, and session details. The worktrees and branches those runs made stay on disk, untouched.
10. These describe RepoCop as running no coding agents:
    - the product's vision, pillars and non-goals;
    - the README;
    - `CLAUDE.md`;
    - `specs/architecture.md`;
    - the safety, agents and testing rules;
    - the lines of the repo template that say RepoCop runs agents.

## Out of scope

- Session events and requests to sessions: `session-events` and `queue-next-step`.
- Reviewing or opening a pull request for the developer's own branches from RepoCop. The repo template's `/review-branch` and `/open-pull-request` do that in the agent's own session (`pull-request-and-review-skills`).
- The rest of the repo template: its skills and `.reviews/review.sh` stay, but for the lines criterion 10 rewords.
- Deleting the worktrees and branches past runs left. RepoCop never deletes them.

## Implementation Notes

- **What goes:**
  - `services/claude.py`, `services/codex.py` and `services/reviews.py`;
  - `services/runner.py`, which runs nothing else;
  - the task page's instruction box and terminal-resume line;
  - the Claude sign-in panel;
  - the requirement page's Start, Review and pull request sections;
  - the `claude-agent-sdk` dependency, and the fake Claude and Codex in `tests/fakes/`.
- **What stays:**
  - a template sync stays a task, with its worktree, branch, page and pull request actions (`services/pull_requests.py`, `services/github.py`);
  - the `tasks` table that records it;
  - the startup step that fails a task left running or queued, with the `app_restarted` reason, for syncs.
- **The workflow line** is built by `workflow_prompt` in `services/runner.py` today. It moves beside `tasks.workflows()`, and `tests/test_architecture.py`'s known agent coupling, and `.claude/rules/agents.md`, move with it.
- **The migration** is forward-only. It drops:
  - past workflow runs and reviews, with their events;
  - the `requirements` table;
  - the `tasks` columns `requirement_id`, `claude_session_id`, `session_pid` and `session_pid_start`;
  - the `pull_requests` rows of requirement branches.

  The data model in `specs/architecture.md` follows.
- **Settings:** the retired ones (`claude_bin`, `anthropic_api_key`, `review_model`, `review_effort`) join the config's list of retired keys.
- **Enforced:** `tests/test_architecture.py` holds criterion 3. Only `git.py` and `github.py` launch processes, and nothing imports `claude_agent_sdk`.
- **The review script:** `.reviews/review.sh` owns its read-only options, and `tests/test_review_script.py` checks the script itself, since `services/codex.py` is no longer there to compare it with.
- **The template's lines that say RepoCop runs agents:**
  - `.reviews/review.sh`'s header ("the way RepoCop runs one");
  - `/address-review`'s "as RepoCop passes it";
  - `/implement`'s "the human or RepoCop chose", unless `implement-starts-its-branch` has rewritten it first.
- **The Copy button** lives in the shared shell script. A test checks its markup, and its copying is checked by hand.
- **Decision records:** one new record covers RepoCop running no coding agents, the product shift included. It supersedes, in whole or in part:
  - ADR-001 (the Agent SDK), ADR-003, ADR-008 and ADR-009 (sessions in worktrees, their permissions and waiting);
  - ADR-010, but for failing a task left running at startup;
  - ADR-012 (a requirement's worktree), ADR-017 (one active task per worktree), ADR-018 and ADR-019 (sign-in and terminal resume);
  - ADR-025 (branch reviews);
  - ADR-023, for requirement branches only.

  ADR-024 (not tied to one agent) stands. ADR-026's `agent/` names stay for sync branches.
- **Rules that shrink:**
  - `.claude/rules/safety.md` › Claude sessions, Reviews, and the parts of Pushing about requirement branches;
  - `.claude/rules/agents.md` and `tests/test_architecture.py`'s agent checks, together;
  - `.claude/rules/testing.md`'s fakes.
