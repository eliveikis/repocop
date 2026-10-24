## Requirement

Repositories stay on the template's rules and skills when the template drops or renames a file, not only when it adds or changes one. Each file the template manages carries a short marker, so sync can tell it from a repository's own file of any name, and removes the marked files the template no longer ships, through the same reviewed pull request as the rest of the sync.

## Acceptance Criteria

1. Every managed file the template ships carries a marker on its first line after any shebang or front matter: `<!-- managed by template -->` in Markdown, `# managed by template` in files whose comments start with `#`. Starter and merged files don't.
2. A repository file that carries the marker, but that the template no longer ships, shows in Sync's plan as removed from the template, picked for deletion by default, and its deletion is committed on the sync branch with the other picks. Edits don't exempt it.
3. A repository with such a file shows as behind the template.
4. A file without the marker is never offered for deletion, whatever its path.
5. A repository whose managed files predate the marker gets it through its next sync, since those files then differ from the template.

## Out of scope

- Files the template dropped before the marker existed, such as `.claude/rules/design.md`: they're deleted by hand in the few repositories that have them.
- Telling whether a managed file was edited.
- A way for a repository to take over a managed file.

## Implementation Notes

- Find marked files with one `git grep` of the compared branch, accepting the marker only as a whole line near the top of a file, so a document that quotes it isn't taken for a managed file. Status reads the plan on every page load, so it stays two git calls per repository, and the grep reads blobs, so it runs under the same no-download guard as `git.read_files`.
- A new file state for a marked file the template doesn't ship, with a `delete` pick. `template_sync.apply` removes picked files in the sync worktree and commits the removals with the rest.
- `.claude/rules/safety.md` › Files says sync deletes only marked files the template no longer ships, on its own branch. `specs/architecture.md` › Template sync gains the state, `templates/README.md` describes the marker, and a decision record covers marking managed files.
- `tests/test_default_template.py` checks that every managed template file carries the marker and no starter file does. This repository's mirrored copies carry it too.
