# REVIEW.md

What a review of changes to RepoCop checks and skips. It only points: each rule is owned by the file linked.

## Check

- The safety invariants in [.claude/rules/safety.md](.claude/rules/safety.md), above all. A change that weakens one is a finding even when its tests pass.
- The invariants in [CLAUDE.md](CLAUDE.md).
- That what is specific to one agent stays in that agent's module, and that no limit is added per repository: [.claude/rules/agents.md](.claude/rules/agents.md).
- That a design decision the change makes is in the specs, as [.claude/rules/specs.md](.claude/rules/specs.md) says.
- That each safety invariant's refusal has a test: [.claude/rules/testing.md](.claude/rules/testing.md).

## Skip

- Running the checks. `make check` and CI run lint, types and tests, and a review's sandbox can't.
- What those checks already enforce: formatting, lint and type errors.
- `uv.lock`, `repocop/static/vendor/` and `specs/changes/archive/`.
