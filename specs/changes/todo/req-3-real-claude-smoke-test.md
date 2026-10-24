# Real Claude smoke test in CI

## Problem

The default test suite never calls Claude. It uses a fake at the boundary of `services/claude.py` (ADR-001), which keeps runs fast, free and deterministic. But nothing then proves that the real Claude Code, driven through the Agent SDK, still behaves the way the fake pretends: which messages arrive, where the session id appears, that a `/skill` call expands inside the worktree, that a follow-up instruction reaches the running session, and that interrupting stops it. An SDK or CLI upgrade could break the coordinator while every test stays green.

## Goal

A small end-to-end smoke test that drives the real Claude Code through the coordinator's own code. It runs at key moments (after merges to `main`, and on demand), never in the standard iterative suite.

## Depends on

req-1 (v0.1): the Claude runner, its task manager, and the fake used by the default suite.

## Requirements

### 1. One scenario, through the real code path

In a throwaway repository with a minimal probe skill, the test registers the repository, sets it up, creates a requirement, and starts a task running the probe skill through the coordinator's runner, with no fake anywhere. It then sends one follow-up instruction to the same session. Prompts stay tiny and deterministic ("reply with this exact word"), so the check doesn't depend on model quality.

### 2. Kept out of normal runs

The smoke tests are marked `@pytest.mark.claude`, which the suite already skips unless `COORDINATOR_TEST_REAL_CLAUDE=1`. A `make smoke` target runs only them. `make check` never does.

### 3. Run at key moments

A CI job runs them on pushes to `main` (that is, after a merge) and on manual dispatch. Pull requests don't run them, so forks never see the secret. Like the coordinator, it authenticates with the Claude subscription by default (ADR-018).

### 4. Bounded cost and blast radius

Each run uses the cheapest suitable model, a spending cap per run (the SDK's `max_budget_usd`), and an overall timeout. It only touches temporary directories, never the developer's repositories or real coordinator database.

### 5. Diagnosable failures

When the smoke test fails, the recorded task events are kept as a CI artifact, so a changed message format can be seen without rerunning.

## Acceptance Criteria

- `make smoke` runs only the real-Claude tests, and `make check` never runs them.
- The smoke test drives the real CLI through `services/claude.py`, with no fake, and checks that: the session id is captured; assistant and result events are recorded; the probe skill expanded in the worktree; a follow-up instruction is answered in the same session; the primary checkout is untouched.
- Each run is capped by model, budget and timeout, and a run that hits a cap fails instead of continuing.
- A CI job runs the smoke test on pushes to `main` and on manual dispatch, using a repository secret. Pull requests don't run it.
- On failure, the recorded events are kept as a CI artifact.

## Scope boundaries

Not part of this change:

- Replacing or weakening the fake-based default suite.
- Browser or UI automation.
- A matrix of models, SDK versions or operating systems.
- Blocking merges on the smoke test. It runs after the merge.

## Open questions

Proposed defaults are marked **→**.

1. **Authentication in CI.** **→** The coordinator's default, the Claude subscription (ADR-018): a long-lived subscription token as a repository secret (to verify: `claude setup-token`). If CI can't use the subscription, run `make smoke` locally instead of in CI. Billing an API key (the `anthropic_api_key` option) only if chosen explicitly.
2. **Model.** **→** The cheapest current model. The probe only asks for exact words, so model quality doesn't matter.
3. **Caps.** **→** `max_budget_usd` of 0.50 per run and a 5-minute timeout for the job.
4. **Triggers.** **→** Pushes to `main` and manual dispatch. Add a nightly schedule later if SDK or CLI upgrades turn out to break things between merges.
5. **Reporting.** **→** A failed run shows as a failed check on `main`'s latest commit. Whether to also open an issue can wait until it's been running a while.
