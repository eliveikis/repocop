<!-- managed by template -->

# Changes

A change is a requirement being delivered: what someone needs, why, and how to tell it's done. [todo/](todo/) holds the changes still to deliver, and [archive/](archive/) the delivered ones, as historical records. Each folder is its own list.

## Lifecycle

Each step after the first runs a skill on the change's path. On the change's own branch you can leave the path out: the skill then works on the branch's requirement ([.claude/rules/specs.md](../../.claude/rules/specs.md) › A branch's requirement).

1. **Propose.** Write the change in `todo/`, named, and in the format, [.claude/rules/specs.md](../../.claude/rules/specs.md) gives: a product story under Requirement, then Acceptance Criteria, and Out of scope, Implementation Notes and Open questions where needed, and commit it. Its file name is its name: on its branch, in its pull request, and in the changes that wait for it.
2. **Review.** Run `/review-requirement specs/changes/todo/<change>.md`, then resolve its blocking questions in the file. From then on the change is fixed: only a human edits it, and only when the work itself changes.
3. **Implement.** Run `/implement specs/changes/todo/<change>.md`. It leaves the change as written, updates the specs as design decisions are made, and writes a decision record for each significant one.
4. **Fold in.** When the change is delivered, run `/complete-change specs/changes/todo/<change>.md`. It folds whatever lasting design isn't in the specs yet into the root design files and area specs, sparingly: the design decisions produced, invariants, models, and flows, not implementation plans or checklists. It also writes any decision record still missing. A reader of `specs/*.md` should never need to read archived changes to understand the current system.
5. **Archive.** The same skill then moves the change to `archive/`, its name stamped with the UTC date and time it was archived, and fixes links to it, in the same PR that completes it.

Archived changes are historical records: don't edit them afterwards. Design files are never archived; they are edited in place.

## Dependencies

A change that can't start until others are delivered names them in its front matter:

```markdown
---
depends-on:
  - bulk-import
---
```

How a name matches a change, and when one counts as delivered, is in [.claude/rules/specs.md](../../.claude/rules/specs.md) › Dependencies. To see what can start now, run `specs/changes/backlog.sh`: it checks every change's list and draws `backlog.md` here, a graph of the changes and then the order they can start in. Its header says how to use it.
