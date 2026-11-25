# Specs

`specs/` is the single authority for design in this repository.

## Root design files

Read these first. Every change is judged against them.

| File | Answers |
|------|---------|
| [product.md](product.md) | **Why and for whom:** vision, design pillars, audience, platform targets, monetization, roadmap |
| [architecture.md](architecture.md) | **How:** goals, main parts and the contracts between them, key flows, where things live (Mermaid) |

## Area specs

One per broad area of the repository, never per feature: each is the one place its area's behaviour is stated, with the reasons that aren't plain from it. Link each here.

| File | Covers |
|------|--------|
| [repositories.md](repositories.md) | Registering a repository, its status and checkout state, fetching it, and removing its merged branches |
| [board.md](board.md) | Where every requirement stands, across the fleet and in each repository |
| [requirements.md](requirements.md) | A requirement's page, storage and backlog, its history of workflow runs, and its review |
| [sessions.md](sessions.md) | The developer's agent sessions as they work, and asking one to run a workflow |
| [template-sync.md](template-sync.md) | Bringing a repository in step with the repo template, and the sync's pull request |
| [repo-template.md](repo-template.md) | What the repo template gives every repository, branch reviews among it |
| [ui.md](ui.md) | The frame every page shares, and how pages stay current |

## Decision records

[decisions/](decisions/) holds one record per architecturally significant choice, one that many later changes must work within: why it was made and what was rejected. Records are history: where one differs from the specs above, the specs hold, so read a record only before changing what it decided. A record superseded whole, or below that bar, moves to `decisions/archive/`, which is never read.

## Changes

A change is a requirement being delivered. The guide in [changes/](changes/) says how one goes from proposal to archive, and how changes wait on each other. Its folders are their own lists, so no change is listed here.
