# ADR-001: Claude Code through the Python Agent SDK

**Status:** superseded by ADR-039 · **Date:** 2026-09-24

## Context

The coordinator has to start a session in a given worktree with the repository's own config, stream its visible output, deliver a user's instruction to that session mid-task, cancel it, and resume it after a coordinator restart. The v0.1 spec (§8) prefers supported mechanisms over terminal emulation.

## Decision

Use the Python Claude Agent SDK (`claude-agent-sdk`, `ClaudeSDKClient`), isolated behind `services/claude.py`. Its behaviour was verified against the real CLI before anything was built on it, and tests fake its client at that boundary.

## Consequences

- Bidirectional sessions, `interrupt()`, `resume`, `cwd`, permission modes and project settings come from a supported, typed wrapper over the CLI.
- Nothing outside `services/claude.py` knows how sessions are driven, so switching to the fallback stays cheap.

## Alternatives rejected

- **Raw CLI per turn** (`claude -p … --output-format stream-json`, then a new `claude -p "<instruction>" --resume <session_id>` process per follow-up): simple, but instructions can only land between turns. It stays the fallback, unbuilt, because the SDK check passed.
- **Terminal emulation:** the spec prefers supported mechanisms.
