# RepoCop

A small, local **fleet manager for agentic repositories**: keep many unrelated Git repositories in step with one repo template (the same rules, skills and spec layout), and see where each one's work stands. Your own coding agent does the work, in your own agent tool; RepoCop runs none.

Write a requirement in your own editor and commit it, then run the repository's workflows in your agent, such as Claude Code: each requirement's page gives the line that runs each one on it, with a Copy button, and the branch to do the work on. The main page's board shows every requirement of every repository by its stage, read from its branches and its pull requests on GitHub, however the work was done, with the agent sessions working on it as they report themselves: working, needing your input, or waiting for your next instruction.

## How it works

```text
~/code/crm-api/                              # your checkout: RepoCop's only write here is a fetch
~/agent-worktrees/crm-api/template-sync-12/  # RepoCop's worktree for a sync, on agent/template-sync-12
```

- Requirements, specs, `CLAUDE.md` and `.claude/` live in each repository. RepoCop only reads them, and keeps only references and the record of its syncs.
- The repo template's files reach a repository through **Sync with template**, committed on a branch in a worktree of RepoCop's own, which you push, review and merge as a pull request.
- Your agent works wherever you run it, in your checkout or a worktree of its own, as many at once as you like. Name its branch after the requirement, as its page says, and the board follows the work.

The design, and the reasons for it, are in [specs/](specs/index.md): the product and its non-goals, the architecture, the decision records, and the changes still to come.

## Prerequisites

| Tool | Needed for | Install (Ubuntu / Debian / WSL) |
|------|------------|---------------------------------|
| [uv](https://docs.astral.sh/uv/) | everything | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | everything | `uv python install 3.12` |
| Git | everything | `sudo apt install git` |
| [GitHub CLI (`gh`)](https://cli.github.com/), optional | the board's pull requests, and a sync's pull request buttons | from GitHub's apt repository, below, then `gh auth login` |

Install `gh` from GitHub's official apt repository:

```bash
(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
	&& out=$(mktemp) && wget -nv -O "$out" https://cli.github.com/packages/githubcli-archive-keyring.gpg \
	&& cat "$out" | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& sudo mkdir -p -m 755 /etc/apt/sources.list.d \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y
```

Then, in a new terminal, `make doctor` checks each tool, and the `gh` sign-in.

Your coding agent, such as [Claude Code](https://code.claude.com/docs/en/setup), runs where you work, not in RepoCop. A repository's `.reviews/review.sh` runs the [Codex CLI](https://learn.chatgpt.com/docs/codex/cli) when you review a branch with it.

## Quick start

```bash
git clone <this-repo> ~/code/orchestrator && cd ~/code/orchestrator
make install                                   # creates .venv via uv
cp repocop.example.yaml repocop.yaml   # optional: see Configuration
make run                                       # → http://127.0.0.1:8765
```

## Configuration

[repocop.example.yaml](repocop.example.yaml) lists every setting with its default and what it does, and says where RepoCop looks for its configuration. Copy it and change what you need: a setting left out keeps its default.

## Reviewing a branch

Every onboarded repository gets `.reviews/review.sh`, which runs Codex's own review of the current branch, read-only. Its header says how to call it and where it saves the review. In a Claude Code session there, `/address-review` then addresses the latest saved review of the branch.

## Development

`make help` lists the commands, and `make check` is what CI runs. The repo is set up for coding agents: [CLAUDE.md](CLAUDE.md), path-scoped rules in [.claude/rules/](.claude/rules/), and workflow skills in [.claude/skills/](.claude/skills/). [REVIEW.md](REVIEW.md) says what a review checks and skips, and [AGENTS.md](AGENTS.md) points other agents, such as Codex, at all of it. This repo follows the same specs and skills convention it brings to other repositories.

## License

RepoCop is licensed under the [MIT License](LICENSE). The repo template in `templates/default-repo/`, whose files are copied into the repositories it onboards, is licensed under [MIT No Attribution](templates/LICENSE), so those copies carry no obligation. The vendored front-end libraries keep their own licenses, listed in [repocop/static/vendor/README.md](repocop/static/vendor/README.md).
