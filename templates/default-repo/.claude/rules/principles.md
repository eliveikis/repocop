<!-- managed by template -->
# Principles

For everything in the repo: specs, rules, skills, scripts, and what it produces, whether code, writing or other media. They keep parts loosely coupled.

- **One owner per piece of knowledge.** A fact, rule or instruction lives only in the spec, rule, skill, module or page that owns it; elsewhere, link to it. Delete any copy you find and link to the owner.
- **Use what a part exposes, not how it works.** Rely on a skill's stated purpose, a spec's stated rule, a module's functions, never on another part's internals or where it sits on disk. Code finds its own files relative to its own package, not through the repo layout.
- **Name things by their responsibility.** Every name, comment, docstring, file header and config comment says what the thing is, does and guarantees. It never lists who calls, reads or runs it: that couples the two, and turns wrong when another consumer arrives. In code, `events_after(task_id, seq)`, not `poll_transcript`. In config, `# how hard a review thinks`, not `# read by review.sh and RepoCop`.
- **Parts don't sequence each other.** A module, skill or workflow works from its inputs, without checking or assuming what ran before or runs after. Ordering belongs to whoever orchestrates: RepoCop, a caller or the human.
- **Guidance goes where it's read when it's needed.** Standards for the repo's work: `.claude/rules/`, scoped by `paths` to the files they govern. A skill's instructions: that skill. What reviews check and skip: `REVIEW.md`, with `AGENTS.md` only pointing other agents at these. Design: `specs/`, from `specs/index.md`, decision records in `specs/decisions/`, and no `docs/` or `design/` folders. `CLAUDE.md`: only what every session needs (project facts, commands, stack, layout, invariants).
- **Add concepts only when a spec calls for them.** No process stages, progress trackers, statuses, config keys or abstraction layers of your own (in code, three similar lines beat a premature base class). If one seems needed, raise it, and record the decision where it belongs.
- **Scripts live beside their only consumer**, in the folder of the skill, test or tool that runs them, so they move and ship together. A top-level `scripts/` is only for repo-wide tooling.
- **Enforce what you can.** Check mechanically whatever can be (a test, a type or lint check, a link or spelling check). Prose alone drifts.
- **Challenge a rule that goes against best practice.** These principles, and the rules, skills and specs built on them, are current judgement, not fixed truth. When following one would go against established best practice or rule out a clearly better option, say so and ask before following it or working around it. Never comply or deviate silently.
