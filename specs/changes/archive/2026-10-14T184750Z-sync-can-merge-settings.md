# Template JSON wins on merge

## Requirement

As a developer, I want every value in the template's JSON files to win in each repo's copy, so that the fleet behaves the way the template says while each repo keeps its own extra settings.

## Acceptance Criteria

1. A repo's merged file is offered for sync when it lacks a template entry, or has a different value for one.
2. Syncing adds the keys and list items the repo lacks, and replaces a value the repo changed with the template's. The repo's own keys and list items stay.
3. A file whose JSON can't be merged is still listed as "can't merge", with the reason.

## Out of scope

- Removing an entry the template no longer has.
- Files that aren't merged JSON.

## Implementation Notes

- The merge's "the repo's value wins" becomes "the template's wins", for plain values and type clashes. Objects are still compared key by key, and lists are still combined.
- A decision record amends ADR-021. `specs/architecture.md` › Template sync and `templates/README.md` follow, including: put a value in a merged template file only when every repo must have it.
