# templates/

`default-repo/` holds the repo template. What it gives a repository is in `specs/repo-template.md`, and how a sync applies it in `specs/template-sync.md`. When you edit it:

- **Keep changes deliberate and self-explanatory.** A change here reaches a repository only when someone syncs and merges it.
- **Mark a new file's kind** in `default-repo/template.toml` when you add it (`specs/template-sync.md` › File kinds): a file it doesn't list is managed. Make anything a repository fills in a starter file. Put a value in a merged file only when every repository must have it, since a repository that changes it is offered it back on every sync.
- **Give every new managed file the marker**, and never a starter or merged file. A file that can have neither comment, such as JSON, can't be managed. `tests/test_default_template.py` checks both.
- **Dropping or renaming a managed file reaches repositories too**, as a sync offers to delete it there: do it on purpose.
- **Use only the one placeholder,** `{{ repo_name }}`. A `.gitkeep` only keeps an empty folder, and isn't part of the template.
- **Don't assume code.** Mark code-specific guidance as such ("In code: …"), and verify through the check command the repository's own `CLAUDE.md` documents, if it has one.
- **Keep license files out of `default-repo/`.** The template's own license is `templates/LICENSE`, beside it.
- **Copies of this repo's own files.** The files listed in `MIRRORED` in `tests/test_default_template.py` are copies of this repo's. Keep them repo-agnostic and change both copies together. The test fails when they differ and prints the command that copies them over.
- **Add a settings entry when a skill gains a command**, in `default-repo/.claude/settings.json` (`specs/repo-template.md` › Settings). `tests/test_default_template.py` checks the skills' commands are covered.
- **Keep `REVIEW.md` tool-neutral:** more than one reviewer reads a file of that name.
- **Don't require the stubs to be filled in.** `CLAUDE.md`, `REVIEW.md`, `specs/product.md` and `specs/architecture.md` stay short stubs.
