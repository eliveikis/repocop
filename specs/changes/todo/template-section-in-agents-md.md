## Requirement

The goal is that developers of RepoCop, and of every repository it keeps in step with the template, can use the same workflows and the same context management in Codex as in Claude Code, so they aren't limited to a single service. This change is the first step, the context: the instructions and rules an agent needs before it starts. Claude Code loads them itself, from `CLAUDE.md` and `.claude/rules/`, but Codex reads only `AGENTS.md`, which in a synced repository is a starter file that sync never updates once the repository has one. So the template will own one marked section of every repository's `AGENTS.md`, pointing Codex at the rules and `REVIEW.md`, which sync adds and keeps up to date while the rest of the file stays the repository's own. RepoCop's own `AGENTS.md` will hold RepoCop's instructions, imported by its `CLAUDE.md`, and carry the same section.

## Acceptance Criteria

1. The template's `AGENTS.md` holds one section, between a begin and an end marker, which the template owns. The rest of the file is a starter's: created when the repository has no `AGENTS.md`, then the repository's own.
2. For a repository whose `AGENTS.md` has no section, Sync's plan lists `AGENTS.md` as behind the template, picked by default, with a diff that appends the section at the end of the file, after one blank line. Applying it commits the file on the sync's branch, with the repository's own text unchanged.
3. When a repository's section differs from the template's, because the template changed it or the repository edited it, the plan offers the template's section in its place, the same way. A repository whose section matches is up to date, whatever the rest of the file holds.
4. An `AGENTS.md` whose markers don't make one section (a begin or an end without the other, an end before its begin, or a second section) is listed as can't merge, with the reason, and isn't offered.
5. A repository with no `AGENTS.md` gets the template's whole file: a pointer to `CLAUDE.md` for the repository's instructions, and the section.
6. A completed sync that brought the section waits until it lands, then shows where it stands, as a sync of any other file does.
7. The template's section says:
   - Read the rules that apply to the work before you start. They are in `.claude/rules/`: a rule with no `paths` in its front matter applies to all work, and one with `paths` only to work on files matching them. An agent that loads the rules itself, as Claude Code does, doesn't read them again.
   - A folder with its own `AGENTS.md` holds guidance for work in it: read it before working on or reviewing files there, unless it's loaded already.
   - A review also follows `REVIEW.md`.
8. The template's `principles.md` allows either layout: `AGENTS.md` as a pointer to `CLAUDE.md` for agents that don't read it, or as the repository's shared instructions, which `CLAUDE.md` imports. Either way it holds the template's section.
9. RepoCop takes the second layout. Its `AGENTS.md` holds the instructions its `CLAUDE.md` holds today, then the template's section, and its `CLAUDE.md` imports `AGENTS.md` and holds only what is Claude Code's own, if anything. A Claude Code session in RepoCop starts with the same instructions as before, and a Codex session starts with them too.

## Out of scope

- The goal's other steps: the skills, the settings and hooks that guard a session, and branch reviews in either agent (`codex-workflows`), and Codex sessions in RepoCop's views and its requests to them (`codex-sessions`).
- A template section in `CLAUDE.md` or another starter file. Claude Code loads the managed rules itself, so `CLAUDE.md` needs nothing from the template.
- A way to keep `AGENTS.md` without the section. Like a merged file's entry, a section the repository removed is offered again on every sync, and unticked.
- Moving a section that's already there: sync replaces it in place.
- Existing repositories' text outside the section, such as the old template's "Read them before you start": sync only appends the section, and the developer edits the rest.
- Switching the template to the layout where `AGENTS.md` holds the instructions and `CLAUDE.md` only imports it. Sync creates the template's `AGENTS.md` whether or not a repository already has a `CLAUDE.md`, and only a pointer works in both cases: an `AGENTS.md` holding the instructions would give Codex `_TBD_` stubs beside a `CLAUDE.md` that has the real ones. A repository can switch to that layout itself, and the section works in either.
- Where `.reviews/review.sh` runs Codex from.

## Implementation Notes

- The section is a new file kind in `template.toml`, `section`, beside starter and merged, which a new decision record adds to ADR-021's. A missing file is created. One that's there takes the states merged files do (identical, behind the template, or can't merge), so the plan, its `merge` pick, and a sync's waiting and landed states carry over.
- The markers are `<!-- begin repo template section -->` and `<!-- end repo template section -->`, each a whole line of its own, whatever its line ending. They are HTML comments of their own, not ADR-032's managed marker, so an `AGENTS.md` that opens with the section isn't taken for a managed file. Once a sync ships them, repositories carry them, so `specs/template-sync.md` › File kinds states them in full, as it states the managed marker. A marker inside a code fence counts like any other, so a file that shows them is listed as can't merge rather than guessed at. `tests/test_default_template.py` lists `AGENTS.md` under the new kind instead of starter.
- `{{ repo_name }}` is replaced in the section as in the rest of the file. A symlinked `AGENTS.md` is refused, as a merged file is. The section is appended after exactly one blank line, in the file's own line endings, and a last line without a newline gets one first.
- How Codex reads `AGENTS.md` (only those files, joined whole from the root down to its working directory, with no import expanded) is checked against the installed Codex CLI, and recorded with its version among the facts in `specs/repo-template.md` › Branch reviews.
- RepoCop's section is a copy of the template's, as the files `MIRRORED` lists are: `tests/test_default_template.py` fails when the two differ, with RepoCop's name in place of `{{ repo_name }}`.
- These follow:
  - `specs/template-sync.md` (File kinds);
  - `specs/repo-template.md` (How it reaches a repository, and Branch reviews' Guidance and verified facts);
  - `specs/repositories.md` (Status: a section behind the template makes a repository `behind`);
  - `specs/architecture.md` (Coding agents: RepoCop's `AGENTS.md` holds its instructions, which `CLAUDE.md` imports);
  - `.claude/rules/principles.md`, in RepoCop and the template (criterion 8);
  - `.claude/rules/safety.md` (Files: sync changes only the section, never the text around it);
  - `templates/README.md` (Mark a new file's kind).
