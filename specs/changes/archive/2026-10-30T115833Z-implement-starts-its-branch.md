## Requirement

Every implementation starts the same way: the developer opens an agent session and asks it to make a branch named after the requirement, off the branch they're on, and then to run `/implement`. `/implement` won't do the first part itself, because it was written for RepoCop to choose and check out the branch first, and RepoCop no longer starts the work (`no-agent-runs`).

`/implement` puts itself on the requirement's branch before it starts: the one it's on if that belongs to the requirement, else an existing branch by the requirement's name, else a new one made off the current branch. One line, `/implement specs/changes/todo/bulk-import.md`, then does the whole job in any agent session, such as agent view's own worktree.

## Acceptance Criteria

1. Given a requirement, `/implement` works on its branch:
   - the current branch, when it belongs to the requirement (`.claude/rules/specs.md` › A branch's requirement);
   - else a branch named exactly the requirement's name, if one exists, which it switches to;
   - else a new branch by that name, made off the current branch, which it switches to.

   Before it starts, it says which of these it did.
2. When that branch exists but another worktree has it checked out, `/implement` stops, names that worktree, and changes nothing.
3. As before, it refuses uncommitted changes other than the requirement file itself, so nothing unrelated comes onto the branch.
4. It never commits on the repository's default branch. With no argument on a branch that belongs to no requirement, it asks for the path and changes nothing, as now.
5. Onboarded repositories get the changed skill through template sync, and RepoCop's own copy matches the template's.

## Out of scope

- Other skills making or switching branches. `/review-requirement` runs anywhere, and `/address-review` and `/complete-change` work on the branch they're on.
- Pushing the branch: `pull-request-and-review-skills`.
- RepoCop's pages.

## Implementation Notes

- The precondition "You are **not** on `main`/`master`. Don't create or switch branches yourself" gives way to criterion 1.
- The template's allowlist gains `git switch`, and `git worktree list` for criterion 2. `tests/test_default_template.py` checks the skill's commands are covered.
- `templates/README.md` says what `/implement` now does about branches.

## Open questions

1. **What a new branch is made off.** **→** The current branch: in an agent view worktree, that is the branch agent view started it from. The alternative is the default branch on `origin` as last fetched, which leaves out local work the developer hasn't pushed.
