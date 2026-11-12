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
4. **Otherwise, write it.** Read the requirements, the branch's commits since it left the default branch (`git log --format=%B origin/<default branch>..HEAD`), and its diff. With one requirement, write:
   - **A title** saying what the change does, imperative, as a commit subject would.
   - **A description** saying what the change does and why, from the requirement's own story rather than the commits' detail; how it was checked: the check command run and its result, the tests added or changed, and any check made by hand, as the work's own reports and commits record them, claiming nothing that wasn't run; and which requirement it delivers, linked to its file as this branch has it, `https://github.com/<owner>/<repo>/blob/<branch>/<path>`, with `<owner>/<repo>` from `gh repo view --json nameWithOwner`.

   With several, write:
   - **A title** saying what merging the branch brings, in one imperative line, not a list of the requirements' names.
   - **A section for each requirement**, in the order they were archived, as their names' stamps have it, with one not archived yet last: its name linked to its file as above, what it does and why, from its own story, and how it was checked on its own branch, as its own commits record.
   - **Also on this branch:** the work none of them covers, from changes added or edited in `specs/changes/todo/` (`git diff --no-renames --name-status origin/<default branch> HEAD -- specs/changes/todo/`), commits made on the branch itself (`git log --first-parent --no-merges origin/<default branch>..HEAD`), and what each merge's resolution changed (`git show --remerge-diff <merge>` for each of `git log --merges --format=%H origin/<default branch>..HEAD`).
   - **How the branch was checked:** only what was run on it as it is now, leaving the rest to CI. A requirement's own checks ran on its own branch, not on this one.

   No agent attribution, in the title, the description or anywhere else (`.claude/rules/commits.md`).
5. **Open it.** `gh pr create --base <default branch> --head <branch> --title "<title>" --body "<description>"`, ready for review rather than a draft. Opening it asks the developer first, as the repository's settings have it.

## Final report

- The pull request's link, and whether it was opened now or already open
- What was pushed: the branch, and how many commits it has that the default branch lacks
- Or, when a precondition failed or the push was refused, why, and that nothing was opened
