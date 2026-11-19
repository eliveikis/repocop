# ADR-035: The app is licensed MIT, and the repo template MIT No Attribution

**Status:** accepted · **Date:** 2026-10-23

## Context

The repository had no license file and declared itself proprietary, so no one else could use, copy or change it. The product isn't worth selling: running and steering agents is a crowded field of free tools, and the buyers who pay need authentication, several users and hosting, all non-goals. Releasing it pays in reputation, feedback and adoption, which need a license that lets people use it. Comparable tools are free: spec kits such as Spec Kit, OpenSpec and BMAD-METHOD are MIT, and agent apps are MIT (OpenHands, opencode) or Apache-2.0 (Codex CLI, Gemini CLI, Goose, Cline).

The repo template differs from the app: its files are copied into other repositories, most of them not the coordinator's author's, and stay there.

## Decision

- The app is licensed MIT, declared in `pyproject.toml` as an SPDX expression with its license files (PEP 639), and Edward Liveikis holds the copyright.
- The repo template is licensed MIT No Attribution (MIT-0), in `templates/LICENSE`, beside `default-repo/` so that sync never copies it. MIT-0 is MIT without the condition to keep the notice, so the files sync writes into a repository carry no obligation.

## Consequences

- Anyone may use, change and redistribute the app, keeping its notice, and the template's files with no conditions at all.
- MIT says nothing about patents or the product's name. Neither is granted, and a trademark policy for the name is separate work.
- The release can't be taken back for copies already made under these terms.
- Claude Code, which the Claude Agent SDK installs, stays Anthropic's under its own terms, which these licenses don't touch.

## Alternatives rejected

- **Apache-2.0 for the app.** Its patent grant and explicit exclusion of the name matter most to companies holding patents. MIT is shorter, better known, and what most comparable free tools use.
- **MIT for the template too.** One license everywhere, as Spec Kit and OpenSpec do, but MIT's notice would then be owed in every repository that received a template file, and nothing puts it there.
- **0BSD or CC0-1.0 for the template.** Equivalent in effect. MIT-0 keeps both licenses in one family, and CC0 is less used for code.
- **A restrictive or source-available license** (AGPL, the Commons Clause). They protect a business the product doesn't have, at the cost of the adoption it's released for.
