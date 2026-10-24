# ADR-034: Requirements have no ids

**Status:** accepted · **Date:** 2026-10-23

## Context

A requirement got a global id from the coordinator's counter when it was created, and its file, branch and worktree were named `req-<id>-<slug>` (ADR-013, ADR-026). The number recorded when an idea was written down, while it read as the order of the work, and a dropped change left a gap. Being global across repositories, the next number could only come from the coordinator, so a change written in the developer's own editor, or worked on from their own agent session, couldn't get one, and in practice went without: a file without an id needed a Track or Assign ID click before work on it could start.

## Decision

- A requirement is a Markdown file in the `todo/` folder of its repository's changes folder, `changes_dir`, whoever wrote it. It has no id: its file name, without `.md`, is its name, its branch is `agent/<name>` and its worktree `<worktrees_root>/<repo>/<name>`.
- The database records a requirement only when something needs a row: its creation in the UI, a kind saved for it, or its first task. The row's key is the database's own and is never shown.
- A requirement's pages are found by its repository and file name, `/repositories/<id>/requirements/<file name>`. A page that loads records nothing, so a requirement nobody has worked on yet has a page without a row.
- Creating a requirement under a file name the repository already uses, in its folder, its archive or the coordinator's records, is refused: the coordinator never deletes branches, so a recorded name's branch may still exist.
- The changes folder replaces the file-name pattern that held the id, in the configuration and for each registered repository. Its `todo/` and `archive/` are named as the repo template's specs convention names them, so every repository has the same layout. A configuration that still names a pattern is refused and says what replaced it.

## Consequences

- Nothing hands out numbers, so work can start on a change wherever it was written, with no step before it.
- Changes that already have an id keep it as part of their name, so their branches, worktrees, tasks and pull requests carry on. Rows keep their keys, and a page address by key, `/requirements/<n>`, leads to the page by file name.
- The order of the work isn't in the names. It comes from what each change says it depends on (ADR-033).
- A file name git won't take as a branch name can't start work: its first task is refused with git's reason, and the file is renamed by hand.

## Alternatives rejected

- **Optional ids, given on request.** Two kinds of name to support, and an Assign ID step that only the coordinator could take.
- **Ids given when work starts.** Ordered as the work is, but still only from the coordinator, and it renames a file under a change that may already be linked.
- **Page addresses by the row's key.** A file nobody has worked on has no row, and recording one when its page loads would change state on a `GET`.
- **No database row at all, the path and kind kept on each task.** It repeats them on every task.
