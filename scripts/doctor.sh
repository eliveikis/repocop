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

# Claude Code CLI — check capabilities, not just presence.
# Oldest version verified with the Agent SDK (specs/architecture.md, ADR-001).
min_claude="2.1.282"
claude_bin="${REPOCOP_CLAUDE_BIN:-claude}"
if command -v "$claude_bin" >/dev/null; then
  ver="$("$claude_bin" --version 2>/dev/null | head -1)"
  help="$("$claude_bin" --help 2>&1)"
  missing=()
  for flag in --output-format --resume --permission-mode; do
    grep -q -- "$flag" <<<"$help" || missing+=("$flag")
  done
  ver_num="$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' <<<"$ver" | head -1)"
  if ((${#missing[@]})); then
    bad "claude ($ver at $(command -v "$claude_bin")) lacks: ${missing[*]} — upgrade Claude Code (see README › Prerequisites)"
  elif [ "$(printf '%s\n%s\n' "$min_claude" "$ver_num" | sort -V | head -1)" != "$min_claude" ]; then
    bad "claude $ver_num is older than $min_claude, the oldest verified with RepoCop — upgrade Claude Code"
  else
    ok "claude $ver"
  fi
else
  bad "claude CLI not found on PATH (or set REPOCOP_CLAUDE_BIN)"
fi

# GitHub CLI — optional: without it, or logged out, only the pull request actions are refused.
gh_use="the pull request actions and the address-pr-comments workflow"
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

# Codex CLI — optional: without it, or signed out, only the Review action is refused.
codex_use="the Review action on a requirement's branch"
if command -v codex >/dev/null; then
  codex_ver="$(codex --version </dev/null 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if codex login status </dev/null >/dev/null 2>&1; then
    ok "codex $codex_ver, signed in (used by $codex_use)"
  else
    warn "codex $codex_ver isn't signed in — optional; run 'codex login' to use $codex_use"
  fi
  # Codex's sandbox uses bubblewrap on Linux, and falls back to a bundled copy without it.
  if [ "$(uname -s)" = "Linux" ] && ! command -v bwrap >/dev/null; then
    warn "bubblewrap not found — Codex uses its bundled copy instead; install it: sudo apt install bubblewrap"
  fi
else
  warn "codex not found — optional; needed for $codex_use"
fi

# WSL note (informational only — RepoCop must not depend on WSL)
if grep -qi microsoft /proc/version 2>/dev/null; then
  case "$PWD" in
    /mnt/*) warn "running from a Windows-mounted path ($PWD); keep repos/worktrees on the Linux filesystem for speed and correct permissions" ;;
    *) ok "WSL detected; working on the Linux filesystem" ;;
  esac
fi

exit $fail
