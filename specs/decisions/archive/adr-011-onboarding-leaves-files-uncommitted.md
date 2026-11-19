# ADR-011: Onboarding leaves the template's files uncommitted

**Status:** superseded by ADR-029 · **Date:** 2026-09-24

## Context

Setting up a repository creates the template's missing files in its human-owned primary checkout.

## Decision

Setup creates only the missing files and commits nothing. The human reviews and commits them.

## Consequences

- The coordinator's only commit in a primary checkout stays the saved requirement file (ADR-004).
