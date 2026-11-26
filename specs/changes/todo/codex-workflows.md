---
depends-on:
  - template-section-in-agents-md
---
## Requirement

The goal is that developers of RepoCop, and of every repository it keeps in step with the template, can use the same workflows and the same context management in Codex as in Claude Code, so they aren't limited to a single service. This change does that for the work itself: the template's skills run in Codex as they do in Claude Code, under the same guardrails, and a branch can be reviewed with whichever of the two agents the developer has. Today Codex finds none of the skills, which live in `.claude/skills/`. The settings and hooks that keep a session from adding agent attribution, reading `.env` files or the decision archive, running Windows programs on WSL, or amending a pushed commit are Claude Code's alone. And `.reviews/review.sh` runs only Codex, so a developer with only Claude Code can't review a branch.

## Acceptance Criteria

1. A Codex session, in a synced repository or in RepoCop, lists the template's skills and runs each one as a Claude Code session does, from the same copy: a skill is written once, in the template, and one sync brings it to both agents.
2. A skill run in Codex finds what it needs as it does in Claude Code: the repository's instructions and rules, its argument, and its own scripts. Where a step uses a feature only one agent has, such as a question with set answers, the skill says what to do in the other.
3. A requirement's page gives each workflow's line for both agents, each with its Copy button: Claude Code's `/implement specs/changes/todo/bulk-user-import.md`, and Codex's. RepoCop lists the workflows from where both agents find them.
4. In a Codex session, the template's settings hold as they do in Claude Code, each as far as Codex can enforce it: commits and pull requests carry no agent attribution; `git push`, `gh pr create` and `gh pr edit` ask first, and the read-only commands and helper scripts the skills run don't; `.env` files and `specs/decisions/archive/` aren't read; on WSL, a command doesn't resolve to a Windows program; and amending a commit that's already pushed is refused. `specs/repo-template.md` › Settings says which of these Codex enforces, and how, and which it can't.
5. `.reviews/review.sh` reviews the branch with Claude Code when Codex isn't installed, or when `REVIEW_AGENT` names Claude Code. The review is read-only, is told what Codex is told, and is saved in `.reviews/` the same way, so `/address-review` picks it up whichever agent wrote it. With Codex installed and no agent named, Codex reviews, as today.
6. RepoCop's own copies of the skills, settings, hooks and review script stay the template's, so a Codex session in RepoCop gets all of the above.

## Out of scope

- Codex sessions in RepoCop's views and in a requirement's history, and RepoCop's requests reaching them: `codex-sessions`.
- Agents other than Claude Code and Codex.
- The agent evals, which run Claude Code only.

## Implementation Notes

- Codex 0.166 mentions a repository's `.agents/skills/`, a project's `.codex/config.toml` and a `hooks.json`. How each works is checked against the installed Codex CLI, and recorded with its version in `specs/repo-template.md`, as the review's facts are.
- One copy for both agents. Claude Code finds skills only in `.claude/skills/`. If Codex's project config can't point it there, a decision record chooses between a link from one folder to the other and sync writing the template's skills to both. Sync and the template's checks handle neither today.
- `argument-hint` and `allowed-tools` are Claude Code's front matter, and `$ARGUMENTS` its substitution: check what Codex does with each.
- The workflows' folder and the line that runs one are among the places `.claude/rules/agents.md` lists. This change adds Codex's beside them, and changes that rule and `tests/test_architecture.py` together.
- `amend-only-unpushed.sh` and `linux-only-path.sh` read Claude Code's hook input and environment (`CLAUDE_ENV_FILE`). Serve Codex from the same scripts where its input allows, rather than a second copy.
- The Claude Code review runs headless, read-only through its permission mode or a list of read-only tools, checked against the installed Claude Code as Codex's facts are. ADR-039 holds: the developer or their agent runs the script, never RepoCop.
- These follow:
  - `specs/repo-template.md` (What every repository gets, Settings, Branch reviews);
  - `specs/requirements.md` (the line that runs each workflow);
  - `specs/architecture.md` (Coding agents);
  - `specs/product.md` (Design pillars: the fourth then holds for skills);
  - `.claude/rules/agents.md`;
  - the `review-branch` skill's description, which names Codex's review.
