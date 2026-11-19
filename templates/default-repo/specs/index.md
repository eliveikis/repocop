# Specs

`specs/` is the single authority for design in this repository.

## Root design files

Read these first. Every change is judged against them.

| File | Answers |
|------|---------|
| [product.md](product.md) | **Why and for whom:** vision, design pillars, audience, platform targets, roadmap, non-goals |
| [architecture.md](architecture.md) | **How:** goals, main parts and the contracts between them, key flows, where things live (Mermaid) |

## Area specs

One per broad area of the repository, never per feature: each is the one place its area's behaviour is stated, with the reasons that aren't plain from it. Link each here.

_None yet._

## Decision records

[decisions/](decisions/) holds one record per architecturally significant choice, one that many later changes must work within: why it was made and what was rejected. Records are history: where one differs from the specs above, the specs hold, so read a record only before changing what it decided. A record superseded whole, or below that bar, moves to `decisions/archive/`, which is never read.

## Changes

A change is a requirement being delivered. The guide in [changes/](changes/) says how one goes from proposal to archive, and how changes wait on each other. Its folders are their own lists, so no change is listed here.
