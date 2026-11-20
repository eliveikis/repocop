# ADR-036: The product is RepoCop, a fleet manager for agentic repositories

**Status:** accepted · **Date:** 2026-10-23

## Context

The product went by three names: the coordinator in its code, configuration and pages, `orchestrator` for its repository, and RepoCop in `specs/product.md`. "Coordinator" is too generic to search for, and three names for one product confuse anyone who meets it. It was also described as a "control plane", which says little about what it does.

## Decision

- **RepoCop**, everywhere it names itself: package, command and distribution (`repocop`), configuration (`REPOCOP_<KEY>`, `repocop.yaml`, `$XDG_CONFIG_HOME/repocop/`), data (`$XDG_DATA_HOME/repocop/repocop.db`), pages, rules, skills and the repo template, including where it names a role ("a RepoCop worktree"). It's short, easy to spell in any language, and no live tool in this space uses it.
- **"A fleet manager for agentic repositories"** describes it. Fleet management is the established name for keeping many members on one baseline while showing each one's state, which is what it does with the repo template and its repositories.
- **Nothing under the former name is read, and nothing is moved for the developer.** A config file or default data folder that exists only under the former name, or an environment variable named with it, stops RepoCop starting, as invalid configuration does, with the command that carries it over. A developer's files are theirs to move, and none is left behind without a word.
- **Stored data names no product.** A task a restart stopped is stored with the reason `app_restarted`, so a later rename leaves stored data alone.
- Decision records and changes keep the name they were written with. A check fails when any other tracked file says the former name, apart from the configuration checks that look for it.

## Consequences

- After the rename merges, the developer moves their config file and data folder as the refusals say, renames the GitHub repository and their checkout, and moves Claude Code's project folder, which is named after the checkout's path.
- A repository registered in its own RepoCop under its old folder shows as `missing`, with its history, until it's added again.
- Records written before this decision still say "the coordinator".

## Alternatives rejected

- **Harbormaster, Concertmaster, RepoRegulator, RepoControl, RepoWrangler.** Longer, harder to spell, or describing control rather than keeping repositories in step. Muster, Regatta and RepoRails were already taken by agent tools.
- **Moving the old config and data on first start.** Convenient, but it moves the developer's files without asking.
- **Reading the old locations as a fallback.** It keeps two names working indefinitely.
- **`repocop_restarted` as the stored reason.** It follows the old pattern, and a later rename would have to rewrite stored data again.
