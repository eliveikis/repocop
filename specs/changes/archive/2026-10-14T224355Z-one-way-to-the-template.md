# One way to bring a repository up to the template

## Requirement

As a developer, I want everything the repo template brings, a new repository's first files included, to arrive one way: on a sync branch, as a pull request I review. That way the coordinator never writes template files into my own checkout, and never offers me the same files twice.

I also want agents in every repository to make one commit per piece of work, so that addressing a review's comments leaves one commit, not one per comment, unless a part is a large change that stands on its own for review.

## Acceptance Criteria

1. A repository whose default branch lacks a template file, or is otherwise behind the template, shows as "behind the template" on the main page and on its own page, linking to Sync with template.
2. Whether a repository is behind is judged from its default branch as committed, so uncommitted files in my checkout neither hide the need to sync nor create one.
3. Set up and its page are gone. The coordinator writes no template files into a primary checkout.
4. A newly added repository is brought up to the template through Sync, like any other.
5. A repository with no commits yet says it needs a first commit before it can be synced.
6. The reports of `address-pr-comments` and `address-review` name the one commit they made once, not a commit per finding.

## Out of scope

- Changing how sync plans, merges or commits files.
- Checking how many commits a branch has.

## Implementation Notes

- The status `needs_setup` becomes "behind the template", taken from the same comparison as the sync plan (`bootstrap.sync_plan(...).up_to_date`). It is read on every page load, so read the default branch's tree once per repository rather than running git for each template file.
- Remove the Set up page and route, `repositories.set_up`, `repositories.setup_plan` and `bootstrap.apply` and `bootstrap.plan`, as nothing else uses them.
- `.claude/rules/safety.md` drops applying missing bootstrap files from the writes the coordinator may make in a primary checkout. A decision record supersedes ADR-011. `specs/architecture.md` › Repository registry and onboarding and › Template sync, `templates/README.md` and the README's onboarding line follow.
- A repository without a GitHub remote still gets its sync branch, which the human merges themselves. The pull request actions already refuse such a remote, with the reason.
- The commit rule is already `.claude/rules/commits.md`, which the template ships and the skills point at. Repositories that haven't synced since still have skills that ask for "one commit per logical group", which is where a commit per comment comes from, so syncing them brings the rule. What still suggests otherwise is the `Commit` column in those two reports' tables: replace it with one `Commit:` line under the table, in both copies.
