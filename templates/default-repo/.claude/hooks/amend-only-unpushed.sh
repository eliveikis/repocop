#!/bin/sh
# managed by template
# PreToolUse hook for Bash: refuse `git commit --amend` when the commit it would replace is already
# on a remote-tracking branch, so pushed history is never rewritten (.claude/rules/commits.md). It
# checks the repository the session is in, and knows only the pushes and fetches it has seen. An
# amend that points git elsewhere (cd, -C, a git dir or work tree) can't be checked, so it is refused.
input=$(cat)

# The command alone, decoded from the hook's JSON, so line breaks are real and no other field counts.
cmd=$(printf '%s' "$input" | awk '
BEGIN { RS = "\001" }
{
  start = index($0, "\"command\"")
  if (!start) exit
  s = substr($0, start + 9)
  if (!match(s, /^[ \t\r\n]*:[ \t\r\n]*"/)) exit
  s = substr(s, RLENGTH + 1)
  n = length(s)
  out = ""
  for (i = 1; i <= n; i++) {
    c = substr(s, i, 1)
    if (c == "\"") break
    if (c != "\\") { out = out c; continue }
    i++
    e = substr(s, i, 1)
    if (e == "n") out = out "\n"
    else if (e == "t") out = out "\t"
    else if (e == "r") out = out "\r"
    else if (e == "u") { out = out " "; i += 4 }  # no check here reads a \u escape
    else out = out e
  }
  printf "%s", out
}')
case $cmd in
*--amend*) ;;
*) exit 0 ;;
esac
case $cmd in
*commit*) ;;
*) exit 0 ;;
esac

elsewhere='(^|[^[:alnum:]_.-])(cd|pushd)[[:space:]]|[[:space:]]-C[[:space:]]|--git-dir|--work-tree|GIT_DIR=|GIT_WORK_TREE='
if printf '%s\n' "$cmd" | grep -Eq "$elsewhere"; then
  echo "This amend runs git through cd, -C, a git dir or a work tree, so this hook can't tell which checkout it amends, or whether that commit is pushed. Run it in the session's checkout without them, or make a new commit instead (.claude/rules/commits.md)." >&2
  exit 2
fi

dir=$(printf '%s' "$input" | sed -n 's/.*"cwd" *: *"\([^"]*\)".*/\1/p')
[ -n "$dir" ] && cd "$dir" 2>/dev/null
head=$(git rev-parse --verify --quiet HEAD) || exit 0
pushed=$(git for-each-ref --contains "$head" --format='%(refname)' refs/remotes | grep -v '/HEAD$' | head -n 1)
pushed=${pushed#refs/remotes/}
[ -n "$pushed" ] || exit 0

echo "$(git rev-parse --short "$head") is already on $pushed, so amending it would rewrite pushed history (.claude/rules/commits.md). Make a new commit instead." >&2
exit 2
