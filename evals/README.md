# Agent evals

An eval answers one question: did my change to the repo template make agents do the work better, or worse? It runs each case, a small task such as "implement this requirement", with the template as it was before your change and as it is after, several times each, and compares how the runs went.

Each run is a real Claude Code session in a throwaway repository of its own, so nothing touches your checkout, and the run sees only the template's own configuration, not yours.

## Before you start

Install [Claude Code](https://code.claude.com/docs/en/setup) and sign in with your Claude subscription (`claude auth login`). Every run is a real session, so it counts against your plan's usage: a full eval of 20 runs takes about 10 to 20 minutes.

## Run it

```bash
make eval                                                     # your working tree against origin's default branch
make eval ARGS="--case implement-refuses-dirty-tree --runs 1" # a quick try: one case, one run a side
make eval ARGS="--before main --after my-branch"              # compare two commits instead
make eval ARGS=--help                                         # every option
```

## Read the results

The eval ends by printing where its summary is: `evals/results/<time>/summary.md`. For each case, it shows how many runs passed on each side, and how long they took and how much they used. A case passes on a side only when every run there passed.

- **Failed** means the agent got the task wrong. The run's row says why, and links its transcript, so you can see what the agent did.
- **Invalid** means the run doesn't count: it hit a usage limit, for example, or loaded some of your own configuration. The row says why.

Runs vary. With 5 runs a side, a difference of one run is noise, so a rare failure needs more runs, such as `--runs 15`, before you call it fixed.

## Add a case

A case is a folder in [cases/](cases/). Its `case.toml` gives the prompt, its `files/` are what the throwaway repository starts with, and its `check.sh` looks at the repository the agent left and decides whether the run passed. Copy one of the cases there to start, and keep it cheap, as it runs ten times an eval. [cases.py](cases.py) describes every part a case can have.

How the eval works, and why it works that way: [specs/evals.md](../specs/evals.md).
