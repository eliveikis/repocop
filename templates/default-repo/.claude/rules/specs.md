---
paths:
  - "specs/**"
---
<!-- managed by template -->

# Specs conventions

- **Root design files:** `specs/product.md` (why, for whom) and `specs/architecture.md` (how) state the current truth and stand alone. Edit them in place, with no history, decisions log or open questions.
- **Decision records** (`specs/decisions/adr-<nnn>-<slug>.md`, titled `# ADR-<nnn>: <the decision>`) say why a significant, hard-to-reverse choice was made. Write one when it's made, numbered after the highest: status and date, context, decision, consequences, and alternatives rejected with why. Once accepted, a record is only edited to mark it superseded by the one that replaces it. Read one only before changing what it decided. A smaller choice's reason goes in the commit message.
- **Area specs** (`specs/<area>.md`) are optional: only for a feature with enough design to deserve one, linked from `specs/index.md`.
- **Changes** live in `specs/changes/todo/` as `<slug>.md`, with no id. Once one is delivered, `/complete-change` folds its lasting design into the specs and moves it to `specs/changes/archive/`, its file name stamped with the UTC time it was archived: `2026-10-14T150616Z-bulk-import.md`. Never edit an archived change or link to one from specs, rules or skills: what lasts is in the specs and decision records.
- **Dependencies.** A change that needs others delivered first lists them in its front matter, one name per line under `depends-on:`, each as `  - <name>`. A change's name is its file name without `.md`, its archive stamp, and the `req-<id>-` prefix older changes carry. A name that matches a change in the archive counts as delivered and no longer holds anything up. Leave it in the list: don't remove it once it's delivered. `specs/changes/backlog.sh` checks every change's list and draws the backlog in `specs/changes/backlog.md`, which git ignores: a Mermaid graph, then the changes in the order they can start. `--check` only checks.
- **A branch's requirement.** A branch belongs to a requirement when its name is the requirement's name, alone or after its last `/`, as `bulk-import` and `agent/bulk-import` both are for `bulk-import.md`. Nothing else ties them: a change is often written and committed apart from the branch that delivers it, so a branch whose name matches no requirement belongs to none, whatever its commits add or edit.
- **A change's format.** No title heading: its file name, and the branch it's delivered on, name it. Its sections, in this order:
  - `## Requirement` (required): a product story, the business case as whoever needs the change sees it: what they need, why, and the solution. A user story's lines without the ritual "As a … I want … so that …": terse, in product terms. Its party can be an end user, a developer or agent, or code calling an API. A fix's story states the broken outcome, who it affects, and the expected behaviour.
  Not: "As a user I can edit my settings so that I can configure the game to my liking", but: "Users edit their settings to suit their needs or their device. A settings page, reachable from the main menu, provides this."
  - `## Acceptance Criteria` (required): outcomes that party can observe. Not which tests to write: `.claude/rules/test-policy.md` decides that.
  - `## Out of scope` (optional).
  - `## Implementation Notes` (optional): only when the existing specs, rules and code don't settle the approach.
  - `## Open questions` (optional): each with a proposed default marked **→**.
- **Size** a change to be delivered in one go, on one branch and one PR. Split anything bigger into separate changes rather than staging work inside one.
- **A change is fixed once reviewed.** It states the work, not its progress: plain, checkable acceptance criteria, and open questions settled before implementation. After that only a human edits it, and only when the work changes; an agent that finds it wrong or incomplete says what should change. Progress shows in the branch and its PR, never in the change, `CLAUDE.md` or the README, and `product.md`'s roadmap stays at the level of themes.
- **Diagrams** are fenced ```` ```mermaid ```` blocks (flowchart, sequenceDiagram, stateDiagram-v2, erDiagram), not images or ASCII art. Keep labels short, quote any with punctuation, and avoid `<...>`, which Mermaid reads as HTML.
- **`specs/index.md` maps the design:** the root design files first, then the area specs, updated when one is added, renamed or removed. It says what decision records and changes are for but never lists them: each folder is its own list.
- Mark unknowns `_TBD: <question>_`. Don't invent product facts.
