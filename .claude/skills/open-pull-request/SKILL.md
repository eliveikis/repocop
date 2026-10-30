---
name: open-pull-request
description: Push the current branch and open its pull request on GitHub, titled and described from its requirement and its work, or push to the one it already has. Use when asked to open, raise or update a branch's pull request.
argument-hint: "[path-to-requirement.md]  (defaults to the branch's requirement)"
---
<!-- managed by template -->

# Open pull request

The requirement the branch delivers: `$ARGUMENTS`

With no path, it is the branch's requirement: the change in `specs/changes/todo/` the branch belongs to, or in the archive beside it once the branch has archived it (`.claude/rules/specs.md` › A branch's requirement). A path given that the branch has archived since is found there too, under its name stamped with when. If it belongs to none, say so, ask for the path, and change nothing. Name the requirement you picked before you start.

## Preconditions (stop and report if any fail, changing nothing)

- `gh auth status` says the GitHub CLI is installed and logged in to the host `origin` is on.
- You are not on the default branch: `git rev-parse --abbrev-ref origin/HEAD` names it as `origin/<branch>` (or, without that ref, `gh repo view --json defaultBranchRef`).
- `git status` is clean, so the pull request shows all the work.
- The branch has commits the default branch on `origin` lacks: `git log --oneline origin/<default branch>..HEAD` isn't empty.

## Steps

1. **Look for its pull request.** `gh pr list --head <branch> --state open --json url,number` finds an open one from this branch, whoever opened it.
2. **Push.** `git push --set-upstream origin <branch>`, under the same name. Never force, in any form (`--force`, `-f`, `--force-with-lease`, a `+` refspec). If the push is refused because `origin` has commits this branch lacks, stop and report that, changing nothing more. Pushing asks the developer first, as the repository's settings have it.
3. **With an open pull request**, that's done: it now has the new commits. Give its link, and don't open a second one.
4. **Otherwise, write it.** Read the requirement, the branch's commits since it left the default branch (`git log --format=%B origin/<default branch>..HEAD`), and its diff, then write:
   - **A title** saying what the change does, imperative, as a commit subject would.
   - **A description** saying what the change does and why, from the requirement's own story rather than the commits' detail; how it was checked: the check command run and its result, the tests added or changed, and any check made by hand, as the work's own reports and commits record them, claiming nothing that wasn't run; and which requirement it delivers, linked to its file as this branch has it, `https://github.com/<owner>/<repo>/blob/<branch>/<path>`, with `<owner>/<repo>` from `gh repo view --json nameWithOwner`.

   No agent attribution, in the title, the description or anywhere else (`.claude/rules/commits.md`).
5. **Open it.** `gh pr create --base <default branch> --head <branch> --title "<title>" --body "<description>"`, ready for review rather than a draft. Opening it asks the developer first, as the repository's settings have it.

## Final report

- The pull request's link, and whether it was opened now or already open
- What was pushed: the branch, and how many commits it has that the default branch lacks
- Or, when a precondition failed or the push was refused, why, and that nothing was opened
