# ADR-005: Server-rendered UI with HTMX, without an SPA or build step

**Status:** accepted · **Date:** 2026-09-24

## Context

- All state is on the server: repositories, worktrees, git output, Claude processes. Pages mostly show server state, so a client-side state layer would only duplicate it.
- The interaction model is simple: lists, forms, a text editor, and panels that refresh themselves.

## Decision

Server-rendered Jinja, with HTMX for live panels and optional page-specific plain JavaScript or vendored libraries where a page needs more. No SPA framework, npm, bundler, or CDN dependency at runtime.

## Consequences

- HTMX polling covers the live parts with HTML attributes alone.
- With no build toolchain, `make run` is the whole deployment, and there's nothing to maintain when the coordinator moves to an always-on host.
- One language (Python) and `TestClient` tests give agents implementing the coordinator a smaller, cheaper surface, with no browser automation.
- Route handlers stay thin, with logic in `services/`, which keeps a later move cheap.

## Revisit if

The UI becomes app-like (heavy client state, drag-and-drop, offline use), or a second client needs a JSON API.
