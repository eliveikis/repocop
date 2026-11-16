# Agent evals: an overview

For a reader who knows agent evals and wants to see quickly what this one does, how it works and what it lacks. How to run it: [README.md](README.md). Its design in full, with the Claude Code CLI facts it relies on: [specs/evals.md](../specs/evals.md).

## What it is

RepoCop ships one repo template, its `CLAUDE.md`, rules, skills, hooks and permissions, to every repository it manages. The eval is a before/after regression test of that template: it runs the same agent tasks with the template before a change and after it, and compares how the runs went.

| | |
|---|---|
| **Compares** | The repo template at two git refs, or at a ref and the working tree. The cases and the runner stay the same, so only the template differs. |
| **Agent** | Claude Code 2.1.282 in headless mode (`claude -p`), on the developer's Claude subscription, one session per run. |
| **Grading** | Deterministic shell checks on the repository the agent leaves. Observations of the transcript are recorded but not scored. |
| **Scale** | 2 cases × 2 sides × 5 runs = 20 sessions, one at a time on one machine, in about 10 to 20 minutes. Run by hand with `make eval`. |

## How a run works

1. **Snapshot both sides.** The template is read at each ref with `git archive`, or from the working tree, without touching the developer's checkout.
2. **Build a sandbox repository.** The case's fixture files, with the template laid over them by RepoCop's own sync code: one commit on `main`, a local bare `origin`, a private temp folder and its own git config.
3. **Set up the scenario.** The case's `setup.sh` changes the repository before the agent starts, such as leaving an unrelated edit uncommitted.
4. **Run one session.** The case's prompt, such as `/implement specs/changes/todo/feature-a.md`, in a fresh headless session. Its stream-json transcript is saved.
5. **Grade the end state.** The case's `check.sh` decides pass or fail. The runner records the repository's state at start and end, so "changed nothing" is a diff.
6. **Update the summary.** A Markdown summary is rewritten after every run: passes per side, medians of steps, time and tokens, permission denials and errors, with a link to each transcript.

Runs alternate sides (before, after, before, …), so drift and rate limits fall on both sides evenly.

**Isolation.** Each run should see the template's configuration and nothing of the developer's. Bare mode needs an API key, which a subscription doesn't have, so isolation comes from flags and the environment, and is then checked on each run:

- Project settings only, no outside MCP servers and no session persistence; memory, claude.ai connectors and auto-update off; an allowlisted environment, so no `ANTHROPIC_*` variables reach a run.
- Each run's init event is checked: a run that loaded the developer's own skills, agents, commands, plugins, MCP servers or hooks is marked invalid.
- No event lists the `CLAUDE.md` files or memory a run loaded. That was checked once against the CLI, and the eval refuses to start when a folder above a run's holds one.

**Scoring.**

- A run **passes** when it is valid, its check holds, and its session ended without an error or a timeout.
- A run is **invalid**, and left out of the score rather than failed, when the service cut it short (a usage limit or an outage), it ran on another model than the eval's other runs, it loaded the developer's configuration, or its setup failed.
- A case passes on a side only when **every** run there passes, so one bad run in five fails it. The eval exits 0 only when every case passes on the after side.

## The cases

| Case | Scenario | Passes when |
|---|---|---|
| `implement-refuses-dirty-tree` | `/implement` on a requirement while an unrelated file has uncommitted changes. | The agent stops and changes nothing: the repository is the same at start and end. |
| `review-requirement-finds-the-gap` | `/review-requirement` on a requirement whose criterion 1 caps an import at 100 users and criterion 3 imports 500 at once. | The review is saved with a verdict other than `yes`, names both 100 and 500, and the repository is unchanged. |

The first real eval, one run of each case on each side, passed 4 of 4. Both sides had the same template, so it is a baseline for noise, not a comparison.

## What is implemented

| Capability | How |
|---|---|
| Paired A/B comparison | The same cases, model and effort on both sides; any ref against another ref or the working tree. The eval says when the two templates are the same. |
| A sandbox per run | A fresh git repository with its own config and a local `origin`, so nothing reaches GitHub, another run or the developer's checkout. |
| Contamination detection | What each run loaded is checked against the developer's own skills, agents, commands, plugins, MCP servers and hooks. |
| Infra failures kept apart | Usage limits, outages, a different model and a broken setup make a run invalid instead of failing it. |
| Deterministic graders | Shell checks on the end state, with a start/end state diff for "changed nothing". |
| Trajectory observations | A regular expression on the agent's first shell command, counted per side but not scored. |
| Metrics | Medians of agent steps, duration, tokens (input, output, cache writes, cache reads), permission denials and tool errors. |
| Artifacts | For each run: the transcript, the repository's state at start and end, and the final reply. The summary survives an interrupted eval. |
| Preflight refusals | It refuses to start when Claude Code is missing or too old or isn't signed in with a subscription, when instruction files sit above the temp folder, and while another eval is running. |
| A tested harness | Hermetic tests drive the runner end to end against a fake Claude Code CLI. `make check` never calls the real agent. |

## What is missing

| Area | Gap | What it means |
|---|---|---|
| Statistics | No confidence intervals, significance tests or effect sizes: only counts and medians. | At 5 runs, 5 passes out of 5 is still consistent with a failure rate of up to about 45% (at 95% confidence), so small regressions don't show. |
| Statistics | The case verdict is strict all-k. Per-side pass counts are shown, but there's no pass@k or pass^k estimate, and no history across evals. | The verdict alone can't tell an occasional failure from a constant one; only the raw counts can. |
| Coverage | Two cases, both refusals or read-only behaviour. No capability task, such as implementing a requirement end to end. | Most skills, and most real work, go unmeasured. |
| Coverage | Single turn only: sessions of several turns, and changes made mid-session, were dropped. | Failures that depend on earlier context can't be written as cases. |
| Coverage | No check that a new case can tell good from bad. The first case tried replayed a real failure, but it passed 5 of 5 on the old skill, so it was dropped. | A case can pass on both sides without showing anything. |
| Grading | No model-graded or human review. A review's content is checked by plain text match. | The quality of the agent's reasoning and writing isn't scored, and a text match can misjudge. |
| Grading | One trajectory signal: no tool-order, step-level or efficiency scoring. | How the agent got to its result barely counts. |
| Scale and operations | Sequential, on one machine, by hand. No CI trigger, scheduling, parallel workers, result store or trends across evals. | Results are Markdown files, compared by eye. |
| Scale and operations | Bound to one subscription's usage limits. Claude Code's cost estimate is available but not reported. | Bigger suites and more runs don't scale. |
| Scope | Claude Code only. Only the repo template is evaluated, not this repository's own configuration, and the eval isn't shipped to managed repositories. | No comparison across agents, and a template sync can't be evaluated in the repository it lands in. |
| Isolation | Runs execute on the host as the developer, with network access: no container or VM. | A misbehaving agent can reach beyond its sandbox repository. |
| Isolation | Contamination checks match by name, and hooks by event, as the CLI doesn't report a hook's command. The developer's `~/.claude` is still read for the sign-in. | A leak with a matching name or event could pass unnoticed. |
| Reproducibility | No seed control, the CLI doesn't report effort, and auto mode's permission decisions are themselves model calls. | Runs vary for reasons the eval can't pin down. |

## Why it is built this way

- **A runner of its own, not `claude plugin eval`.** Claude Code's built-in eval runner loads no project-level configuration and compares a plugin with no plugin, not two versions. What's tested here is project configuration. ([ADR-044](../specs/decisions/adr-044-agent-evals-run-claude-code-with-a-runner-of-their-own.md))
- **The developer's subscription, not an API key.** It matches how the template is used day to day and needs no separate billing, though every run counts against the plan's usage. The price is weaker isolation, made up for by checking each run.
- **Permission allow rules passed back in.** A headless session in a folder no one has trusted drops the project's allow rules, so the runner passes the repository's own rules with `--settings`, rather than trusting the folder in the developer's own configuration.
- **Deterministic grading first.** Shell checks give the same answer every time. Model or human review can be added later without changing how cases are written.

## Where it lives

| Path | What |
|---|---|
| `evals/` | The runner, and one folder per case in `cases/` |
| [evals/README.md](README.md) | How to run an eval and read its results |
| [specs/evals.md](../specs/evals.md) | The design, and the Claude Code CLI facts it was checked against |
| `tests/test_evals.py` | End-to-end tests against a fake Claude Code CLI |
