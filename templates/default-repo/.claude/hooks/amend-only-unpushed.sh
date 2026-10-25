#!/bin/sh
# managed by template
# PreToolUse hook for Bash: refuse `git commit --amend` when the commit it would replace is already
# on a remote-tracking branch, so pushed history is never rewritten (.claude/rules/commits.md). It
# checks the repository the session is in, and knows only the pushes and fetches it has seen.
input=$(cat)
case $input in
*--amend*) ;;
*) exit 0 ;;
esac
case $input in
*commit*) ;;
*) exit 0 ;;
esac

dir=$(printf '%s' "$input" | sed -n 's/.*"cwd" *: *"\([^"]*\)".*/\1/p')
[ -n "$dir" ] && cd "$dir" 2>/dev/null
head=$(git rev-parse --verify --quiet HEAD) || exit 0
pushed=$(git for-each-ref --contains "$head" --format='%(refname)' refs/remotes | grep -v '/HEAD$' | head -n 1)
pushed=${pushed#refs/remotes/}
[ -n "$pushed" ] || exit 0

echo "$(git rev-parse --short "$head") is already on $pushed, so amending it would rewrite pushed history (.claude/rules/commits.md). Make a new commit instead." >&2
exit 2
