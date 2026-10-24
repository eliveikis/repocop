# ADR-032: Managed template files carry a marker, so sync can delete one the template retires

**Status:** accepted · **Date:** 2026-10-20

## Context

Sync compared only the files the template ships (ADR-021). When the template dropped or renamed a managed rule or skill, repositories kept the old file: still loaded into every session, and maybe contradicting the new one. Sync couldn't remove it, because nothing told a file the template once shipped apart from a repository's own file, which could have any name, a template path included.

## Decision

- Every managed file the template ships carries a marker on its first line after any shebang or front matter: `<!-- managed by template -->` in Markdown, `# managed by template` in files whose comments start with `#`. Starter and merged files don't, since they're the repository's own or hold its own entries.
- A file on the compared branch that carries the marker, but that the template no longer ships, is `removed from the template` in the plan. Like every offered file, it's picked by default (ADR-030), here for deletion. The deletion is committed on the sync's branch with the rest, and reaches the default branch only through the pull request the human merges.
- A file without the marker is never offered for deletion, whatever its path.
- The plan finds marked files with one `git grep` of the branch, and reads the ones the template doesn't ship in the same call as the template's files. It's still two git calls, so status can read it on every page load. The marker counts only on its line after any shebang or front matter, so a document that quotes it isn't taken for a managed file.

## Consequences

- A managed file must be in a format that has one of these comments. A file without either, such as JSON, can be starter or merged, not managed. `tests/test_default_template.py` checks the template's managed files carry the marker and no other file does.
- Editing a managed file doesn't exempt it from deletion. Removing the marker, or moving it, does, and that's how a repository keeps a copy for its own use.
- A repository whose managed files predate the marker gets it with its next sync, since its files then differ from the template.
- A file the template dropped before the marker existed isn't found, so it's deleted by hand.
- The grep reads every text file on the branch. A partial clone that lacks any of them can't be compared, rather than download it on a page load, and the plan's cost grows with the repository's size.

## Alternatives rejected

- **List retired paths in the template's manifest.** The template would have to remember every name it ever shipped, and a repository's own file at one of those paths would be deleted.
- **Remember what each sync wrote.** In the coordinator's database, it would be a copy of repository state, which the database never stores. In a file in the repository, it's another file to keep in step, and repositories synced before it have none.
- **Accept the marker anywhere in a file.** A document that quotes the marker would be offered for deletion.
- **Delete only files identical to a version the template shipped.** It needs every past version, and an edited file would be kept forever.
