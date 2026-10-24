## Requirement

Changes get written well before anyone works on them, often before anyone knows the order the work will go in. The coordinator numbers each one as it's created, so `req-<id>` records when an idea was written down while it reads as the order of the work, and a dropped change leaves a gap. The number is global across repositories, so only the coordinator can hand out the next one: a change written in the developer's own editor, or worked on from their own agent session, can't get one, and in practice goes without.

Requirements have no ids. A change is created, edited and worked on under its file name alone, such as `bulk-import.md`, wherever it was written. Changes whose file names already carry an id keep it as part of their name, and work as they do now.

## Acceptance Criteria

1. New requirement writes `<slug>.md` in the repository's requirements folder and commits that file alone, as today. Its page opens on it.
2. Every Markdown file in the requirements folder is a requirement, whoever made it, and every workflow starts on it once it's committed. There is no Track or Assign ID step.
3. A requirement's first task creates the branch `agent/<file name>` and the worktree `<worktrees_root>/<repo>/<file name>`, and its later tasks, reviews and pull request use them. For a file named `req-<n>-<slug>.md`, that's the branch it has today.
4. Pages, page titles, error messages, the task header, commit messages and pull request titles name a requirement by its file name without `.md`. Nothing shows a requirement as `req-<n>` except as part of that name.
5. Creating a requirement under a file name the repository already uses, in its requirements folder, in its archive (whatever the time stamp) or among the requirements the coordinator has recorded, is refused with the reason, and nothing is written.
6. A repository's requirements are configured by their folder, not a file-name pattern. A configuration that still names a pattern is refused, and says what replaces it. Registered repositories keep their folders.
7. Requirements that already have an id keep their files, branches, tasks, reviews and pull requests, which work as before. Nothing is renamed or renumbered.

## Out of scope

- Renaming existing requirements, branches or archived changes.
- Ordering or prioritising requirements.
- Task ids and decision-record numbers.
- A requirement's kind, which its page still shows.

## Implementation Notes

- `.claude/rules/specs.md`, the reviews rule, the Lifecycle in `specs/index.md` and the repo template already describe changes without ids. The coordinator, `CLAUDE.md` invariant 1, the README's example and `specs/architecture.md` change here.
- A decision record covers the change, and ADR-013, ADR-016 and ADR-026 are marked superseded in the parts it replaces.

## Open questions

1. **Where a requirement's key lives.** A requirement still needs a database row for its tasks, and today that row's key is the id in its file name (ADR-013). **→** The row's key becomes the coordinator's own, seen only in page addresses. Existing rows keep their keys, so nothing migrates. The alternative drops the table and keeps the path and kind on each task, which repeats them on every task.
2. **Reusing a name.** Without an id, a new change can take the name of an archived one whose branch still exists, since the coordinator never deletes branches. **→** Refuse it (criterion 5), saying to pick another name. A clash with a branch the coordinator didn't record is refused at the first task, as now. The alternative allows the name and lets the first task fail on the branch, after the file is committed.
3. **The configuration key.** **→** `requirements_dir`, the folder relative to the repository, defaulting to `specs/changes/todo`. A forward-only migration turns each registered repository's stored pattern into its folder. The alternative keeps `requirement_path_pattern` with only `{slug}` in it, a pattern that can only ever be a folder plus `.md`.
