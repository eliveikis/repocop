# RepoCop

A small, local **fleet manager for agentic repositories**: keep many unrelated Git repositories in step with one repo template (the same rules, skills and spec layout), see where each one's work stands, and start, watch and steer coding agents' work in them. Claude Code runs the work today, and Codex can review a branch before its pull request.

Pick a repository and a requirement in it, and start a workflow: one of the skills the repository has committed. RepoCop runs Claude in a **dedicated git worktree and branch**, so your own checkout stays yours. You watch the session live, send it instructions, and inspect its diff, all from one page. Before the pull request, one click has Codex review the branch on your machine, and another hands that review to a task that addresses it. When the work is ready, one click pushes the branch and opens its pull request on GitHub.

## How it works

```text
~/code/crm-api/                               # your checkout: RepoCop never runs agents here
~/agent-worktrees/crm-api/bulk-user-import/   # RepoCop's worktree, on branch agent/bulk-user-import
```

- Requirements, specs, `CLAUDE.md` and `.claude/` live in each repository. RepoCop keeps only references and execution history.
- The repo template's files reach a repository through **Sync with template**, as a branch and pull request you review.
- Each task gets its own Claude Code session in its requirement's worktree, with the repository's own instructions, rules, skills and settings. Many run at once, one per worktree.
- You can keep running `claude` in your own checkout while tasks run.

The design, and the reasons for it, are in [specs/](specs/index.md): the product and its non-goals, the architecture, the decision records, and the changes still to come.

## Prerequisites

| Tool | Needed for | Install (Ubuntu / Debian / WSL) |
|------|------------|---------------------------------|
| [uv](https://docs.astral.sh/uv/) | everything | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | everything | `uv python install 3.12` |
| Git | everything | `sudo apt install git` |
| [Claude Code](https://code.claude.com/docs/en/setup) | running tasks | `curl -fsSL https://claude.ai/install.sh \| bash`, then run `claude` once to log in |
| [GitHub CLI (`gh`)](https://cli.github.com/), optional | the pull request buttons and `address-pr-comments` | from GitHub's apt repository, below, then `gh auth login` |
| [Codex CLI](https://learn.chatgpt.com/docs/codex/cli), optional | branch reviews | `curl -fsSL https://chatgpt.com/codex/install.sh \| sh` (again to update), then `codex login` |
| bubblewrap, optional (Linux) | Codex's sandbox, which otherwise uses a bundled copy | `sudo apt install bubblewrap` |

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

Then, in a new terminal, `make doctor` checks each tool, its version against the oldest one verified with RepoCop, and the `gh` and Codex sign-ins.

## Quick start

```bash
git clone <this-repo> ~/code/orchestrator && cd ~/code/orchestrator
make install                                   # creates .venv via uv
cp repocop.example.yaml repocop.yaml   # optional: see Configuration
make run                                       # → http://127.0.0.1:8765
```

## Configuration

[repocop.example.yaml](repocop.example.yaml) lists every setting with its default and what it does, and says where RepoCop looks for its configuration. Copy it and change what you need: a setting left out keeps its default.

## Reviewing by hand

Every onboarded repository gets `.reviews/review.sh`, which runs the same Codex review as RepoCop's Review action, without RepoCop. Its header says how to call it and where it saves the review. In a Claude Code session there, `/address-review .reviews/<that file>` then addresses the review.

## Development

`make help` lists the commands, and `make check` is what CI runs. The repo is set up for coding agents: [CLAUDE.md](CLAUDE.md), path-scoped rules in [.claude/rules/](.claude/rules/), and workflow skills in [.claude/skills/](.claude/skills/). [REVIEW.md](REVIEW.md) says what a review checks and skips, and [AGENTS.md](AGENTS.md) points other agents, such as Codex, at all of it. This repo follows the same specs and skills convention it brings to other repositories.

## License

RepoCop is licensed under the [MIT License](LICENSE). The repo template in `templates/default-repo/`, whose files are copied into the repositories it onboards, is licensed under [MIT No Attribution](templates/LICENSE), so those copies carry no obligation. The vendored front-end libraries keep their own licenses, listed in [repocop/static/vendor/README.md](repocop/static/vendor/README.md). Claude Code, which the Claude Agent SDK installs alongside RepoCop, is Anthropic's, under Anthropic's own terms.
