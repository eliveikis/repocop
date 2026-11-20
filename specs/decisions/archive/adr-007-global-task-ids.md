# ADR-007: Task ids are one global counter

**Status:** accepted · **Date:** 2026-09-24

## Context

Tasks run across unrelated repositories and are referred to in the UI and in branch names such as `chore/template-sync-43`.

## Decision

Task ids come from one global integer counter that is never reused, separate from requirement ids, and are shown as `#42`.

## Consequences

- An id alone identifies a task anywhere.
