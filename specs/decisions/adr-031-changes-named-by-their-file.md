# ADR-031: A change is a product story, named by its file

**Status:** accepted · **Date:** 2026-10-15

## Context

A change had three names: the `# <name>` heading inside it (ADR-013), its file name, and the branch named after that. They drifted apart, since a heading could be edited and a file name couldn't. Changes were also written as user stories, or as task lists with little of why the work was wanted.

## Decision

- A change has no title heading. Its file name, without `.md`, is its name: in the coordinator's pages, its commit messages and its pull request's title. The name given when a change is created makes the file name, and is fixed from then on, as the slug already was.
- A change is a product story, then acceptance criteria its party can observe, with optional Out of scope, Implementation Notes and Open questions, in that order. `.claude/rules/specs.md` holds the format, and `/review-requirement` checks a change against it.

## Consequences

- A change can't be renamed in the coordinator. Its file name and branch already couldn't be.
- An existing change's heading is part of its text: shown and edited with the rest, and no longer read as its name.
- A pull request's title is the file name, for example `req-12-bulk-import`, rather than a sentence.

## Alternatives rejected

- **Keep the heading as the name.** A third name, which could say something other than the file and branch it belongs to.
