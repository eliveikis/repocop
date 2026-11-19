# ADR-037: RepoCop has no requirement editor, and its own sessions are kept but not extended

**Status:** accepted · **Date:** 2026-10-26

## Context

Developers write requirements in their own editor and run the workflow skills from their own agent session in the repository, where they have search, a terminal and the agent that has followed the work so far. RepoCop's requirement editor competed with those tools and lost, and it was the only reason RepoCop committed in a human-owned checkout (ADR-004). Its task page is a weaker chat window than an agent's own, and running and steering agents in parallel worktrees is a field crowded with tools that do it better. A requirement's kind, feature or fix, was set only in that editor, and since every branch RepoCop names starts `agent/` (ADR-026), it changed nothing.

## Decision

- **Requirements are read-only in RepoCop.** A requirement's page shows its text, in the folder or archived, with an "Open in editor" link to its file in the primary checkout when `editor_url` is set. Nothing in RepoCop creates, edits or commits a requirement file: the developer writes and commits it in their own editor, and the repository's page says where.
- **RepoCop makes no commit in a primary checkout.** Its only write there is a fetch.
- **The developer's own agent runs the workflows.** A requirement's page gives, for each of the repository's workflows, the line that runs it on the requirement, such as `/implement specs/changes/todo/bulk-import.md`, from the code that builds a RepoCop task's first prompt, so the two never differ. It names the branch to do the work on: the requirement's name, which tells a review which requirement the branch is for.
- **A requirement has no kind.** It's gone from the pages and, by a forward-only migration, from the database.
- **RepoCop's own tasks stay as they are:** template sync, branch review, pull requests, and a workflow run in a RepoCop worktree. The workflow run is kept but no longer extended: no permission prompts on the task page, sandboxed sessions, trust checks or real-Claude smoke test. The changes that proposed them are deleted; git history keeps them.

## Consequences

- A task start on a requirement with uncommitted changes is refused as before, and its reason names the file to commit first. RepoCop no longer offers to commit it.
- A requirement is recorded only by its first task.
- An editor link to a file leaves out a slash right after `{path}`, since a slash there makes an editor such as VS Code open a folder.
- A developer's own branch for a requirement, `bulk-import`, is apart from RepoCop's `agent/bulk-import`. RepoCop doesn't yet review, push or open a pull request for a branch it didn't create.
- The non-goals gain an editor for repository files and a chat interface beyond today's task page.

## Alternatives rejected

- **Keep the editor but drop its commit.** It still competes with the developer's editor, and a saved but uncommitted file can't reach a worktree, so every save would need a commit by hand.
- **Read the kind from the file's front matter.** Every change would then carry a field that nothing uses.
- **Remove RepoCop's own workflow runs too.** They still work, reviews and pull requests build on their worktrees, and removing them gains nothing now. Extending them is what stops.
- **Leave the session changes in `todo/`.** The backlog would keep showing them as work still wanted.
