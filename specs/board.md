# Board

The main page answers the product's question across every repository at once: is each one in step with the repo template, and where does its work stand? Stages are read from the repository itself and GitHub, however and by whomever the work was done, and nothing on the board acts: it only shows, as the work is done in the developer's own agent.

## The main page and a repository's

The main page's table has a row per repository: its template status, with how many files a sync would offer one behind it, how many of its requirements are in each stage, linking to its page, and its checkout. Under it, **Active now** shows the requirements in progress or in review in any repository, as cards. To do and Delivered stay off it: merged across repositories they mean nothing, as each repository orders its own backlog.

A repository's page has its board: every stage of its own requirements, in its backlog's order ([requirements.md › Dependencies](requirements.md#dependencies)), with only the latest few delivered shown and the rest folded.

## Stages

A requirement is in the first stage that applies:

| Stage | When |
|-------|------|
| Delivered | archived within the past week by its archive stamp, in the checkout or on the default branch on `origin` as last fetched. One archived earlier, or without a stamp, isn't shown |
| In review | a branch that belongs to it has an open pull request |
| In progress | a branch that belongs to it has commits that default branch lacks, or a session working on it is working, needs input or has completed its turn |
| To do | anything else in the requirements folder that `origin` hasn't archived, however long ago; its card names what it waits on |

A card's stage is as of the page load.

- **Branches.** A branch belongs to a requirement by its name (`.claude/rules/specs.md` › A branch's requirement), whoever made it, local or on `origin` as last fetched. The board goes by that alone, not by the changes a branch delivers by archiving them. A card names each one, the commits the default branch lacks, and whether `origin` has them all. The local tip counts when there is one.
- **No default branch from `origin`.** A repository whose checkout lacks it says to fetch first, and its cards show no branch state. A partial clone that lacks the archive on it is never made to download it: the board says it can't be read.
- **Pull requests** are read from GitHub, and only those whose branch is in the registered repository count, not a fork's. They are read after the page renders, each repository's side by side, so the page never waits for GitHub: the board fills in with them, and on the main page each repository's counts. Without JavaScript, a link reloads the page with them read. A repository whose pull requests can't be read says why (no `gh`, logged out, not on github.com, no answer in time), and its cards keep the stage they have without them.
- **A branch still here.** On a repository's page, a delivered card whose requirement's branch is among the repository's merged branches says so, and links to that list ([repositories.md › Merged branches](repositories.md#merged-branches)): the board itself still acts on nothing.
- **Sessions.** A card shows the sessions working on its requirement ([sessions.md › What a session shows](sessions.md#what-a-session-shows)). On the main page, a repository's sessions that work on no requirement with a card there show in its row of the table, as other sessions, so no running work goes unseen; a repository's page lists all of its sessions anyway. A repository whose default branch on `origin` lacks the hook that records sessions gets a note saying a template sync brings it.
- **Readiness.** A card to do or in progress says whether its requirement's reviews find it ready to implement ([requirements.md › A requirement's review](requirements.md#a-requirements-review)).
