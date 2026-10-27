---
name: review-requirement
description: Critically review a requirement/spec Markdown file for ambiguity, gaps, contradictions, testability and scope before implementation starts. Use when asked to review, critique or sanity-check a requirement in specs/changes/.
argument-hint: "[path-to-requirement.md]  (defaults to the branch's requirement)"
allowed-tools: Read, Grep, Glob, Bash(git log:*), Bash(git ls-files:*), Bash(git branch --show-current), Bash(git rev-parse:*), Bash(git merge-base:*), Bash(git diff:*)
---
<!-- managed by template -->

# Review requirement

Review the requirement at `$ARGUMENTS`. With no path, review the branch's requirement: the change in `specs/changes/todo/` the branch belongs to (`.claude/rules/specs.md` › A branch's requirement). If it belongs to none, say so and ask for the path. Name the requirement you picked before you start.

This review is **read-only**. Do not edit the requirement or any code. Produce findings and let the human decide.

## Steps

1. Read the requirement in full, then read `CLAUDE.md`, `specs/index.md` and the authoritative specs it lists (`specs/*.md`), and any spec the requirement references. Skim the parts of the repo it touches so your findings are grounded in what's really there, not a hypothetical version.
2. Evaluate it against the checklist below.
3. Report back in the output format.

## Checklist

- **Product fit:** does the change serve the vision and pillars in `specs/product.md`? Does it conflict with a higher-ranked pillar or a stated non-goal? If `specs/product.md` or `specs/architecture.md` is missing or still mostly `_TBD_`, say so as a low-severity finding. It isn't blocking.
- **Format:** does it follow the change format in `.claude/rules/specs.md`? Flag a missing required section, a title heading, a task list instead of a product story, criteria that aren't outcomes its party can observe, implementation detail outside Implementation Notes, and notes missing where the existing specs, rules and code don't settle the approach.
- **Ambiguity:** terms or behaviours that two competent contributors would deliver differently.
- **Gaps:** what the work will need that the requirement doesn't say. In code: error cases, empty states, limits, concurrency, restart/recovery, security, or migration. In writing or other media: audience, length, sources, and rights to images or quotes.
- **Contradictions:** with itself, with the authoritative specs, with what's already in the repo, or with repository rules in `.claude/rules/`.
- **Testability:** every acceptance criterion should be verifiable by an automated test or a concrete manual step. Flag the ones that aren't.
- **Smells and best practices:** does the requirement encourage practices that conflict with established best practices or current standards? Ask focused questions where context is missing and suggest concrete improvements.
- **Scope:** anything that belongs out of scope, and anything that is missing yet necessary for the stated Definition of Done. Is it small enough to deliver in one go, on one branch and one PR? If not, propose how to split it into separate requirements.
- **Hidden dependencies:** external tools, versions, credentials, or network access the requirement assumes.

## Output format

```markdown
## Summary
<2–3 sentences: is this ready to implement? yes / yes-with-assumptions / no>

## Blocking questions
1. <question> — why it blocks, proposed default

## Findings
| # | Severity (high/med/low) | Section | Finding | Suggested change |

## Assumptions I would make if unanswered
- ...
```

Keep it concrete. Cite section headings or line numbers, and don't restate the requirement back.
