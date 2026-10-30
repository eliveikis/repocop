# ADR-038: The board reads each requirement's stage from its repository and GitHub

**Status:** accepted · **Date:** 2026-10-28

## Context

RepoCop knew only the work it ran itself, but most work happens in the developer's own agent sessions, which make their own branches and worktrees and open their own pull requests. Its main page couldn't answer the product's question: where does each repository's work stand? ADR-023 kept GitHub out of every page load, so even a pull request RepoCop could see on GitHub stayed unknown until someone clicked an action on the branch's page.

## Decision

- **The stage is read, not recorded.** Each requirement's stage comes from its repository and GitHub on each page load: its changes folder and archive, in the checkout and on the default branch on `origin` as last fetched; the branches named after it, local or on `origin`, whoever made them; and its branches' open pull requests. RepoCop stores nothing about it, and doesn't need to have done the work.
- **A page may read from GitHub; it never writes to it.** The main page's board reads each repository's open pull requests with one read-only `gh pr list`, with a timeout, after the page renders. This supersedes ADR-023's rule that no page load calls GitHub. Pushing and opening, editing or reviewing a pull request stay on an explicit click.
- **Nothing fetches on a page load**, as ADR-022 decided. Branches and the default branch are as of each checkout's last fetch, and a Fetch all button fetches every repository on request.

## Consequences

- A stage can lag the remote until the next fetch, and the board says so for a checkout that lacks the default branch from `origin`.
- The main page costs more: a fixed number of git calls per repository, whatever its number of branches, and one `gh` call per repository read side by side after the page renders, so GitHub never holds the page up.
- A branch that isn't named after a requirement doesn't count. That rule, in `.claude/rules/specs.md`, is how work done outside RepoCop is tied to a requirement.
- Without `gh`, logged out, or off github.com, a repository's cards keep the stage they have without pull requests, and the board says why.

## Alternatives rejected

- **Record stages as RepoCop's tasks move them.** Most work isn't RepoCop's tasks, and a recorded stage drifts from the repository, which owns the knowledge (`specs/product.md` › Design pillars).
- **Fetch on page load to keep stages current.** It writes to every primary checkout on every visit and waits on the network: ADR-022 stands.
- **Ask GitHub once per branch.** It costs a `gh` call for every branch on every page load; one listing per repository answers for all of them.
- **Webhooks or polling GitHub between page loads.** Webhooks need RepoCop reachable from GitHub, a non-goal; polling is cost with no reader.
