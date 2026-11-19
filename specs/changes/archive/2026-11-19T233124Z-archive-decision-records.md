---
depends-on:
  - lean-specs
  - area-specs
---
## Requirement

RepoCop has 43 decision records, and most record how a feature behaves or were replaced, in part or whole, by later ones, so an agent that follows a citation reads history it takes for design. Under the specs rule `lean-specs` brings, RepoCop keeps only the 14 records that meet the bar and archives the rest. This comes after `area-specs`, so that what each record decided is checked against the area spec it now belongs in.

## Acceptance Criteria

1. RepoCop's `specs/decisions/` holds only the 14 records the Implementation Notes keep. The rest are in `specs/decisions/archive/`, unedited.
2. Whatever an archived record decided that still holds is stated in RepoCop's specs or rules.
3. Nothing but a record or a change cites an archived record: a rule, `CLAUDE.md`, code or a test that cited one cites the spec or rule that now states its decision, or nothing.

## Out of scope

- Editing the kept records: their citations of archived ones stay.
- Any change to how RepoCop or the template behaves.

## Implementation Notes

- **The records kept:**
  - **The stack:** ADR-002 (SQLite without an ORM) and 005 (the server-rendered UI).
  - **What RepoCop writes in a repository:** 006 (sync on its own branch), 022 (fetch), 029 (the template only through sync) and 041 (requests to sessions).
  - **Its contracts with the template and with repositories:** 020 (the template doesn't assume code), 021 (file kinds), 032 (the marker) and 034 (requirement identity).
  - **What it depends on:** 023 (GitHub through `gh`), 038 (stages read, not stored), 039 (no coding agents) and 040 (the session log).

  Every other record moves. Each is superseded whole, or its choice is feature behaviour, a convention the specs rule owns, or a product stance that `product.md`, `LICENSE` or `.claude/rules/safety.md` already states. ADR-027, 042 and 043 move too: the area specs state the merge rule and the stored formats they decided in full, with their reasons, and ADR-040 is the one record of a repository writing what RepoCop reads.
- **Moving.** Records move with `git mv`, so each shows as a rename with nothing changed. The pull request lists each one with the spec or rule that now states what it decided, or says it no longer holds.
- **What carries over** from an archived record is its decision. Its reason carries over, in a clause, only where the behaviour looks arbitrary without it and the record was the only place it was stated.
- **Citations to replace** include `.claude/rules/safety.md` (ADR-015, 030, 037), `CLAUDE.md` (037), `repocop/db.py` (007, 013), `services/bootstrap.py` and `services/template_sync.py` (027), `services/repositories.py` (015), `services/requirements.py` (028), `tests/test_db.py` (007), and ADR-027 wherever `area-specs` put `templates/README.md`'s citation of it.
