# Specs

`specs/` is the single authority for design in this repository.

## Root design files

Read these first. Every change is judged against them.

| File | Answers |
|------|---------|
| [product.md](product.md) | **Why and for whom:** vision, design pillars, audience, platform targets, roadmap, non-goals |
| [architecture.md](architecture.md) | **How:** structure, data model, key flows (Mermaid) |

## Area specs

Optional. Add a `specs/<area>.md` when a feature earns its own design page, and link it here.

_None yet._

## Decision records

[decisions/](decisions/) holds one record per significant, hard-to-reverse choice: why it was made and what was rejected. The design files above stand without them, so read a record only before changing what it decided.

## Changes

A change is a requirement being delivered. The ones still to deliver are in [changes/todo/](changes/todo/), and delivered ones in [changes/archive/](changes/archive/), as historical records. Each folder is its own list, so no change is listed here.

## Lifecycle

1. **Propose.** Create the change in `changes/todo/` (RepoCop's UI can do this for you), named, and in the format, `.claude/rules/specs.md` gives: a product story under Requirement, then Acceptance Criteria, and Out of scope, Implementation Notes and Open questions where needed.
2. **Review.** Run `/review-requirement specs/changes/todo/<change>.md`, then resolve its blocking questions in the file. From then on the change is fixed: only a human edits it, and only when the work itself changes.
3. **Implement.** Run `/implement specs/changes/todo/<change>.md`. It leaves the change as written, updates the specs as design decisions are made, and writes a decision record for each significant one.
4. **Fold in.** When the change is delivered, run `/complete-change specs/changes/todo/<change>.md`. It folds whatever lasting design isn't in the specs yet into the root design files and area specs, sparingly: the design decisions produced, invariants, models, and flows, not implementation plans or checklists. It also writes any decision record still missing. A reader of `specs/*.md` should never need to read archived changes to understand the current system.
5. **Archive.** The same skill then moves the change to `changes/archive/`, its name stamped with the UTC date and time it was archived, and fixes links to it, in the same PR that completes it.

Archived changes are historical records: don't edit them afterwards. Design files are never archived; they are edited in place.
