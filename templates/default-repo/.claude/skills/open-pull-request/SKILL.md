---
name: open-pull-request
description: Push the current branch and open its pull request on GitHub, titled and described from its requirements and its work, or push to the one it already has. Use when asked to open, raise or update a branch's pull request.
argument-hint: "[path-to-requirement.md ...]  (defaults to the branch's requirement and the changes it delivers)"
---
<!-- managed by template -->

# Open pull request

The requirements the branch delivers: `$ARGUMENTS`

With one or more paths, those are its requirements. A path given that the branch has archived since is found in the archive beside its folder, under its name stamped with when. With none, they are the branch's own requirement and the changes it delivers (`.claude/rules/specs.md` › A branch's requirement):

- the change in `specs/changes/todo/` the branch belongs to, or in the archive beside it once the branch has archived it;
- each change archived on the branch that the default branch on `origin` hasn't archived: `git diff --no-renames --diff-filter=A --name-only origin/<default branch> HEAD -- specs/changes/archive/` lists them.

If there are none, say so, ask for the path, and change nothing. Name the requirements you picked before you start.

## Preconditions (stop and report if any fail, changing nothing)

- `gh auth status` says the GitHub CLI is installed and logged in to the host `origin` is on.
- You are not on the default branch: `git rev-parse --abbrev-ref origin/HEAD` names it as `origin/<branch>` (or, without that ref, `gh repo view --json defaultBranchRef`).
- `git status` is clean, so the pull request shows all the work.
- The branch has commits the default branch on `origin` lacks: `git log --oneline origin/<default branch>..HEAD` isn't empty.

## Steps

1. **Look for its pull request.** `gh pr list --head <branch> --state open --json url,number` finds an open one from this branch, whoever opened it.
2. **Push.** `git push --set-upstream origin <branch>`, under the same name. Never force, in any form (`--force`, `-f`, `--force-with-lease`, a `+` refspec). If the push is refused because `origin` has commits this branch lacks, stop and report that, changing nothing more. Pushing asks the developer first, as the repository's settings have it.
3. **With an open pull request**, that's done: it now has the new commits. Give its link, and don't open a second one.
4. **Otherwise, write it.** An archived requirement's summary is the body of the commit that archived it, which `git log --format=%B origin/<default branch>..HEAD -- <its archived path>` shows: a lead of one or two sentences on why and what, then an index of one line per place the work landed. Where that body has none, or the requirement isn't archived yet, read the requirement at the path this branch has it and write the lead and index from its story. Read the branch's other commits since it left the default branch (`git log --format=%B origin/<default branch>..HEAD`) for what else is on it. Don't run the check command and don't review: the work's own branch and CI do that, and the description says nothing about how it was checked. With one requirement, write:
   - **A title** saying what the change does, imperative, as a commit subject would.
   - **A description** in three parts: its lead; its index; and the requirement, linked to its file as this branch has it, `https://github.com/<owner>/<repo>/blob/<branch>/<path>`, with `<owner>/<repo>` from `gh repo view --json nameWithOwner`.

   With several, write:
   - **A title** saying what merging the branch brings, in one imperative line, not a list of the requirements' names.
   - **A lead** of one or two sentences on why the branch exists.
   - **One bullet per requirement**, in the order they were archived, as their names' stamps have it, with one not archived yet last: its name linked to its file as above, and its lead.
   - **Also on this branch:** one line per piece of work none of them covers, from changes added or edited in `specs/changes/todo/` (`git diff --no-renames --name-status origin/<default branch> HEAD -- specs/changes/todo/`), commits made on the branch itself (`git log --first-parent --no-merges origin/<default branch>..HEAD`), and what each merge's resolution changed (`git show --remerge-diff <merge>` for each of `git log --merges --format=%H origin/<default branch>..HEAD`).

   The description fits on one screen: it says enough to decide whether to open the requirement or the commits, and points at them for the rest. When it runs longer, cut first the detail the commits or the diff carry.

   No agent attribution, in the title, the description or anywhere else (`.claude/rules/commits.md`).
5. **Open it.** `gh pr create --base <default branch> --head <branch> --title "<title>" --body "<description>"`, ready for review rather than a draft. Opening it asks the developer first, as the repository's settings have it.

## Final report

- The pull request's link, and whether it was opened now or already open
- What was pushed: the branch, and how many commits it has that the default branch lacks
- Or, when a precondition failed or the push was refused, why, and that nothing was opened
