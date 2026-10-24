# ADR-008: Headless permissions: `acceptEdits` plus the repository's allowlist

**Status:** accepted · **Date:** 2026-09-24

## Context

Coordinator sessions run headless, so nobody is at a terminal to answer a permission prompt. Sessions must inherit the repository's own config (spec §6), and permissions are never bypassed.

## Decision

Run with `acceptEdits` plus the repository's own `.claude/settings.json` allowlist, and never bypass permissions. A denied action shows up in the transcript, and the human answers through the instruction box.

## Consequences

- A tool call outside the allowlist, and every `ask` rule, is refused rather than asked about.
- Widening what a session may do means editing the repository's committed settings.
