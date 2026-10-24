#!/bin/sh
# managed by template
# SessionStart hook: on WSL, keep Windows directories off the PATH of Claude's Bash commands, so a
# missing Linux tool fails instead of resolving to a Windows one, and tell Claude why.
# Elsewhere it does nothing.
grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null || exit 0
[ -n "$CLAUDE_ENV_FILE" ] || exit 0

# Single-quoted, so it filters the PATH of each shell that sources it rather than this hook's.
printf '%s\n' 'export PATH="$(printf %s "$PATH" | tr : "\n" | grep -v "^/mnt/[a-z]/" | paste -sd: -)"' >>"$CLAUDE_ENV_FILE"
echo "This machine runs WSL, and Windows programs are kept off PATH. If a Linux tool is missing, stop and say so; don't use a Windows program instead."
