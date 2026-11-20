# ADR-033: Each change declares what it depends on, and the backlog is drawn from those on request

**Status:** accepted · **Date:** 2026-10-23

## Context

Changes in `specs/changes/todo/` often need others delivered first, and whoever orders the backlog couldn't see which. A few changes said so in a prose `## Depends on` section, which nothing could check and which went stale once the dependency was delivered. Spec-driven tools are converging on the same answer: the dependent item lists its prerequisites by id, a check refuses unknown ids and cycles, and the view is generated, not drawn by hand. Hand-kept order files go stale, as OpenSpec's own did.

## Decision

- A change lists the changes it needs in its front matter: `depends-on:`, then one `- <name>` per line. A change's name is its file name without `.md`, any archive stamp and any `req-<id>-` prefix, so it survives an id being assigned and the change being archived. Front matter keeps the list readable by a script, and it's already how rules and skills declare theirs.
- One relation only, "delivered first". A dependency is delivered once its change is in the archive. The change that needs it is left as it is, as a reviewed change is fixed.
- The coordinator reads the lists on each page load. The requirements list groups the changes by level, and each requirement's page shows what it's blocked by and what it blocks. A problem is shown, and the changes it holds up are listed apart, rather than failing the page.
- The template ships `specs/changes/backlog.sh`, plain `sh` and `awk`, which checks the lists and draws the backlog in a git-ignored `specs/changes/backlog.md`. `--check` only checks. The coordinator never runs it, since a repository's scripts aren't the coordinator's to run, so the rules live in both, and a test holds the two to the same levels and the same problems.

## Consequences

- The backlog graph isn't on GitHub. It's drawn on request, in the editor, or seen in the coordinator.
- The rules exist twice, in Python and in `awk`, and change together.
- Cycles are found by the script itself, not `tsort`, whose reports differ between GNU and BSD and name one loop at a time, so the two couldn't promise the same problems.
- A name is only compared with the folder's file names, never used to build a path.

## Alternatives rejected

- **A hand-kept graph file**, such as `specs/changes/todo/_dependencies.md`. It's a second copy of what each change owns, it conflicts whenever parallel branches add or archive changes, and the coordinator would list it as a requirement, since every Markdown file in that folder is one.
- **A committed, generated graph**, such as a block in `specs/index.md`. The coordinator commits a requirement file alone when it saves one (ADR-004), so the graph would be stale after most edits, and a check that it's current would fail branches that didn't cause it. `specs/index.md` is also a starter file, which sync never updates.
- **The issue tracker's dependencies** (GitHub's "blocked by"). The truth would sit outside the repository, agents would need the network and GitHub to see it, and GitHub is optional and called only on a click (ADR-023).
- **The coordinator running `backlog.sh`.** It would run a repository's code on a page load.
