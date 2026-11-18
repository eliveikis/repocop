## Requirement

Decision records in repositories built on the repo template pile up, and they cost more than they explain. The specs rule asks for a record for any "significant, hard-to-reverse choice". So records get written for how features behave, restate the specs, and stay beside them after later records replace parts of them. An agent that follows a citation then reads history it takes for design. The specs rule raises the bar to architecturally significant choices, and makes the specs the truth over any record. Records that no longer earn their place move into an archive no one reads. Every repository gets the rule on its next template sync.

RepoCop pays off its own debt under the rule in the same change. Its `specs/architecture.md` holds every feature's behaviour, and `templates/README.md` restates the repo template's design; both are split into area specs. Of its 43 records, it keeps only the 13 that meet the bar.

## Acceptance Criteria

1. `.claude/rules/specs.md`, in RepoCop and in the repo template, says what the Implementation Notes give. Its other bullets are unchanged.
2. Nothing in RepoCop or the template still describes decision records by the old bar or contradicts the rule: not `/implement`, `/complete-change`, `specs/changes/README.md`, the specs indexes, the introductions of the `architecture.md` files, or `CLAUDE.md`. `/complete-change` puts a feature's behaviour in its area spec, not in `architecture.md`.
3. A new repository's `specs/architecture.md` stub prompts for what the rule says `architecture.md` holds.
4. Claude Code refuses to read anything in `specs/decisions/archive/` with its file tools. This holds in RepoCop and in every repository that syncs the template's `.claude/settings.json`.
5. `make check` fails when:
   - a record in `specs/decisions/` or its archive is misnamed or untitled, or shares its number with another;
   - a cited ADR id has no record in either folder;
   - specs, rules, skills or code cite an archived record.
6. RepoCop's `specs/architecture.md` holds only what the rule says it does. Every feature's behaviour that it or `templates/README.md` stated is in an area spec linked from `specs/index.md`, with nothing lost and nothing changed in meaning. `templates/README.md` keeps only how to work in that folder.
7. Every link to a section that moved points to where it now is.
8. RepoCop's `specs/decisions/` holds only the 13 records the Implementation Notes keep. The rest are in `specs/decisions/archive/`, unedited, and whatever they decided that still holds is stated in RepoCop's specs or rules.

## Out of scope

- Moving an onboarded repository's records or restructuring its specs.
- Rewriting code docstrings that restate an area spec, beyond fixing their links.
- Any change to how RepoCop or the template behaves: the restructure moves text and removes duplicates.

## Implementation Notes

- **Phases.** Deliver this in three commits, in this order, each with `make check` green:
  1. The rule and the template: criteria 1 to 5.
  2. RepoCop's specs restructured: criteria 6 and 7.
  3. RepoCop's records archived: criterion 8. This comes after the restructure, so that what each record decided is checked against the area spec it now belongs in.
- **The rule.** Its first three bullets become these four:
  - **Root design files:** `specs/product.md` (why, for whom) and `specs/architecture.md` (how) state the current truth and stand alone. Edit them in place, with no history, decisions log or open questions. `architecture.md` says how the system is built: its goals, its components and what each may depend on, the contracts between them, its key flows, and where things live. It gives each component its role in a few lines and links to the area spec for how its features behave, rather than saying it.
  - **Area specs** (`specs/<area>.md`) are optional: only for a feature with enough design to deserve one, linked from `specs/index.md`. An area spec is the one place its feature's behaviour is stated, with the reasons that aren't plain from it.
  - **Decision records** (`specs/decisions/adr-<nnn>-<slug>.md`, titled `# ADR-<nnn>: <the decision>`) say why an architecturally significant choice was made: one that many later changes must work within and that is costly to undo. Examples are a boundary between components or what one may depend on, a contract between them (a protocol, a stored format, a determinism rule), the platform, the engine or a core library, and how environments are built. How a feature behaves is not one, however hard it was to settle: its area spec says it, and a smaller choice's reason goes in the commit message. Write a record when its choice is made, numbered after the highest in `specs/decisions/` and its archive: status and date, context, decision, consequences, and alternatives rejected with why.
  - **A record is history; the specs are the truth.** Where a record and a spec differ, the spec holds, and no change reconciles older records with it. Once accepted, a record is edited only to say what superseded it: a line at its top names the record that replaced a part of it. A record replaced whole, or whose choice isn't architecturally significant, moves to `specs/decisions/archive/`, and the links of records that point at it follow the move. Read a record only before changing what it decided. Never load the archive, or cite an archived record from specs, rules, skills or code.
- **The archive deny rule.** Add `Read(./specs/decisions/archive/**)` to `permissions.deny`, beside the `.env` entries. Archived changes stay readable, because skills read the changes a branch archived.
- **The split.** This is the expected shape. An area too small for its own spec joins the nearest one:

  | Area spec | From |
  |---|---|
  | `repositories.md` | Repository registry and onboarding; Remote links |
  | `board.md` | Fleet board |
  | `requirements.md` | Requirements and the developer's agent; Requirement storage; A requirement's history; A requirement's review |
  | `sessions.md` | Session events; Session requests |
  | `template-sync.md` | Template sync; Status machine; Pull requests |
  | `repo-template.md` | Branch reviews, and the design in `templates/README.md` |
  | `ui.md` | UI approach |

  `architecture.md` keeps the Principle as its goals, Components, the Data model, Coding agents, Configuration in short, and Deployment portability. It names each contract between components and where that contract is stated in full.
- **The records kept:**
  - **The stack:** ADR-002 (SQLite without an ORM) and 005 (the server-rendered UI).
  - **What RepoCop writes in a repository:** 006 (sync on its own branch), 022 (fetch), 029 (the template only through sync) and 041 (requests to sessions).
  - **Its contracts with the template and with repositories:** 021 (file kinds), 032 (the marker) and 034 (requirement identity).
  - **What it depends on:** 023 (GitHub through `gh`), 038 (stages read, not stored), 039 (no coding agents) and 040 (the session log).

  Every other record moves. Each is superseded whole, or its choice is feature behaviour, a convention the specs rule owns, or a product stance that `product.md`, `LICENSE` or `.claude/rules/safety.md` already states.
