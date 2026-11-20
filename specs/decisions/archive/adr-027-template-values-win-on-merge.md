# ADR-027: The template's values win when sync merges JSON

**Status:** accepted · **Date:** 2026-10-14

## Context

A merged template file, today `.claude/settings.json`, is JSON that each repository also adds its own entries to (ADR-021). Sync added the entries a repository lacked, but wherever both had a value, the repository's won. So a value the template sets for the whole fleet, such as turning off bypass-permissions mode, could be changed in one repository and sync would never offer to put it back. The template is meant to be the authority on what it sets.

## Decision

- When sync merges a file, the template's value wins wherever both have one that isn't an object or array on both sides, and wherever their types differ.
- Objects are still compared key by key, and arrays still combined: the template's missing items are appended. Keys and array items only the repository has stay where they are.
- A merged file is offered whenever merging would change it: when it lacks a template entry, or has a different value for one. It is picked by default, as merges were, and lands on the sync branch for review.
- This supersedes ADR-021's "only adds the template's missing entries". The rest of ADR-021 stands.

## Consequences

- A merged template file should hold only values every repository must have. A value a repository legitimately wants different is offered back on every sync.
- An entry the template drops stays in the repositories that have it: nothing records what the template used to ship.

## Alternatives rejected

- **Naming the keys the coordinator controls, and letting the repository win elsewhere.** A second list to keep in step with the template, when the template already says what it wants.
- **Overwriting the whole file.** It would drop what each repository adds of its own.
