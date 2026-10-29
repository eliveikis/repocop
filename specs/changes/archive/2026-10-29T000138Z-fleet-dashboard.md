---
depends-on:
  - no-requirement-ids
---
## Requirement

The coordinator only knows about work it ran itself, so work done in the developer's own agent sessions, which is most of it, never shows on its pages. What the developer needs from it is the answer to `specs/product.md`'s question across every repository at once: is each one in step with the repo template, and where does its work stand?

The main page becomes the fleet's dashboard. A board shows every requirement in every repository by its stage, read from the repository itself (its changes folder, its branches and its pull requests), however the work was done. Each repository shows how far it is behind the template, and one click fetches them all.

## Acceptance Criteria

**The board**

1. The main page shows a board of the requirements in every registered repository that isn't `missing` (open question 1). Each requirement is in the first of these stages that applies, and its card names its repository and links to the requirement's page:
   - **Delivered:** archived, in the checkout or on the default branch on `origin` as last fetched, within the past week by its archive stamp (open question 2). Changes archived earlier aren't shown.
   - **In review:** a branch that belongs to it has an open pull request on GitHub.
   - **In progress:** a branch that belongs to it has commits that the default branch on `origin` lacks, as last fetched, or a coordinator task is active on it.
   - **To do:** anything else in the `todo/` folder. A card that waits on a change not yet delivered names it.
2. A branch belongs to a requirement when its name is the requirement's name, or ends with `/` followed by that name: `bulk-import`, `agent/bulk-import` and `eddie/bulk-import` all belong to `bulk-import.md`. Local branches and `origin`'s branches as last fetched both count, whoever made them.
3. An In progress or In review card names each branch that belongs to it, how many commits the default branch lacks, and whether `origin` has all of them. An In review card links to its pull request, and a card with an active coordinator task links to that task.
4. The board appears without waiting for GitHub, and pull requests fill in once GitHub answers. A repository whose pull requests can't be read (no `gh`, logged out, not on github.com, or no answer in time) says why, and its cards keep the stage they have without them. Reading pull requests changes nothing on GitHub.
5. A repository whose checkout lacks the default branch from `origin` says to fetch first, and its cards show no branch state.

**The fleet**

6. A repository behind the template says how many files a sync would offer, and links to its Sync page.
7. A **Fetch all** button on the main page fetches every registered repository that isn't `missing`, each exactly as its own Fetch does. Each repository's result is shown, and one failure doesn't stop the others.

## Out of scope

- Acting on the branches the board shows. Reviews and pull request actions stay on a requirement's page, for the coordinator's own branches.
- Detecting or tracking the developer's own agent sessions. The board reads only the repository and GitHub.
- Syncing several repositories in one action. Every sync shows its files and their diffs before anything is written.
- Following a pull request between page loads, or webhooks.
- `ui-refresh`'s sidebar, breadcrumbs and switcher.

## Implementation Notes

- `specs/architecture.md` and `.claude/rules/safety.md` › Pushing change with it: "no page load pushes or calls GitHub" becomes "pushes or writes to GitHub". `.claude/rules/reviews.md` and its template copy say when a branch belongs to a requirement in the same words as criterion 2.
- A decision record covers reading each requirement's stage from its repository and GitHub, including pull requests read when a page loads, and supersedes that part of ADR-023. ADR-022's rule that nothing fetches on a page load stands.
- Open pull requests come from one read-only `gh` call per repository, not one per branch, in `services/github.py` with a timeout, counting only pull requests whose head is in the registered repository rather than a fork. htmx loads them after the page renders, so it is loaded on the main page as well, and without JavaScript the board shows without them.
- A repository's branches and their commits come from a fixed number of git calls, not one per branch. Fetch all can run the fetches side by side, each with its own timeout.

## Open questions

1. **Where the board lives.** **→** On the main page, above the repository table, so one page answers the product's question. The alternative is a page of its own, linked from the main page.
2. **How long a delivered change stays on the board.** **→** A week from its archive stamp. An archived change without a stamp is never shown. The alternative shows the last few delivered per repository.
