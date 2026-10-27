---
depends-on:
  - no-requirement-ids
---
## Requirement

Developers write requirements in their own editor and run the workflow skills from their own agent session in the repository, where they have search, a terminal and the agent that has followed the work so far. The coordinator's requirement editor competes with those tools and loses, and it is the only reason the coordinator commits in a human-owned checkout. Its task page is a weaker chat window than the agent's own, and running and steering agents in parallel worktrees is a field crowded with tools that do it better.

Requirements are read-only on the coordinator's pages, with a link that opens them in the editor. A requirement's page gives the line that starts each workflow in the developer's own agent. The coordinator's own tasks stay as they are: template sync, branch review, pull requests, and a workflow run in a coordinator worktree, which is kept but no longer extended.

## Acceptance Criteria

1. A requirement's page shows its text read-only, whether it is in the folder or archived, with an "Open in editor" link to its file in the primary checkout when `editor_url` is configured. Nothing creates, edits or commits a requirement file: there is no New requirement page, no Save and no Commit.
2. The coordinator makes no commit in a primary checkout. Its only write there is a fetch.
3. The repository's page says how to add a requirement: a Markdown file in the `todo/` folder of its changes folder, named for the change.
4. Starting a task on a requirement with uncommitted changes is refused, as now, and the reason says to commit the file first.
5. No page shows or asks for a requirement's kind (open question 1).
6. A requirement's page gives, for each of the repository's workflows, the line that runs it on this requirement in the developer's own agent session, such as `/implement specs/changes/todo/bulk-import.md`, ready to copy. It names the branch to do the work on, which is the requirement's name, so that a review, and the coordinator, can tell which requirement the branch is for.
7. Starting a workflow in a coordinator worktree, branch review, addressing a review, template sync and the pull request actions work as they do now.

## Out of scope

- Reviewing, pushing or opening a pull request for a branch the coordinator didn't create, such as one the developer's own agent works on.
- Extending the coordinator's own sessions: permission prompts, sandboxing, trust checks or a real-Claude smoke test (open question 2).
- Choosing which workflow comes next. The page offers every workflow, as Start does.
- Showing work done outside the coordinator: `fleet-dashboard`.
- Rendering a requirement's Markdown.

## Implementation Notes

- `specs/product.md` changes with it: the Vision's paragraph on running agents, the Target audience, pillars 1 and 3 (the agents they speak of are the ones the coordinator starts), the Roadmap, and Non-goals, which gain an editor for repository files and a chat interface beyond today's task page. `CLAUDE.md` invariant 1, `.claude/rules/safety.md` › Human-owned checkout, `specs/architecture.md`, the README, and the Lifecycle's first step in `specs/index.md` and its template copy change too.
- A decision record covers the product's scope: no editor, and the coordinator's own sessions kept but not extended. It supersedes ADR-004.
- The line to copy comes from the code that builds a task's own prompt, so the two can't differ, and no page template builds it (`.claude/rules/agents.md`).

## Open questions

1. **A requirement's kind.** Once the editor goes, nothing sets it, and since every coordinator branch starts `agent/`, it changes nothing. **→** Drop it from the pages and from the database, with a forward-only migration. The alternative reads it from the file's front matter, a field every change would then carry.
2. **The session changes in the backlog.** `req-3` (real-Claude smoke test), `req-4` (permission prompts on the task page), `req-5` (sandboxed sessions) and `req-6` (untrusted repositories) all extend the coordinator's own sessions. **→** Delete all four with this change, and their links from `specs/architecture.md`. Git history keeps them, should the sessions be extended again. The alternative leaves them in `todo/`, where the backlog keeps showing them as work still wanted.
