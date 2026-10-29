#!/usr/bin/env bash
# Verify host prerequisites for running / developing RepoCop.
# Exit non-zero if a hard requirement is missing.
set -uo pipefail

fail=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; fail=1; }

echo "RepoCop doctor"

# Python 3.12+
if command -v python3 >/dev/null; then
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    ok "python3 $(python3 -c 'import platform; print(platform.python_version())')"
  else
    bad "python3 >= 3.12 required (found $(python3 --version 2>&1)); uv can install one: uv python install 3.12"
  fi
else
  bad "python3 not found"
fi

# uv
if command -v uv >/dev/null; then
  ok "uv $(uv --version | awk '{print $2}')"
else
  bad "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# git with worktree support
if command -v git >/dev/null; then
  if git worktree list >/dev/null 2>&1 || git help worktree >/dev/null 2>&1; then
    ok "$(git --version)"
  else
    bad "git found but 'git worktree' unavailable"
  fi
else
  bad "git not found"
fi

# GitHub CLI — optional: without it, or logged out, the board shows no pull requests and a
# template sync's pull request actions are refused.
gh_use="the board's pull requests and a template sync's pull request actions"
if command -v gh >/dev/null; then
  gh_ver="$(gh --version | head -1 | awk '{print $3}')"
  if gh auth status --hostname github.com >/dev/null 2>&1; then
    ok "gh $gh_ver, logged in to github.com (used by $gh_use)"
  else
    warn "gh $gh_ver isn't logged in to github.com — optional; run 'gh auth login' to use $gh_use"
  fi
else
  warn "gh not found — optional; needed for $gh_use"
fi

# WSL note (informational only — RepoCop must not depend on WSL)
if grep -qi microsoft /proc/version 2>/dev/null; then
  case "$PWD" in
    /mnt/*) warn "running from a Windows-mounted path ($PWD); keep repos/worktrees on the Linux filesystem for speed and correct permissions" ;;
    *) ok "WSL detected; working on the Linux filesystem" ;;
  esac
fi

exit $fail
