#!/bin/sh
# managed by template
# Hook on Claude Code's session events: records what this session does, one JSON line per event in
# RepoCop's session log format, in <git common dir>/repocop/sessions/<session id>.jsonl, a folder
# every worktree of the repository shares and no commit holds. A line names the session, the
# time, the folder and branch it is in and the agent's process; beyond those it holds only a
# workflow's name and the first line of its argument, the tool a permission wait is for, or why
# the session closed. Never a prompt, a command or what the agent said. It runs async and always
# exits 0, so it never delays or fails the session. A session's start removes the logs that have
# gone a week without an event. Needs only sh, awk and git.
LC_ALL=C
export LC_ALL

input=$(cat)

# The payload's top-level strings, and those of its tool_input, picked out by a small JSON scanner
# that stops at tool_response. Each is printed as JSON holds it, escapes and all, one per line in
# a fixed order; an argument only up to its first line break, and at most 200 characters.
parsed=$(printf '%s' "$input" | awk '
function firstline(raw,    out, i, n, c, e, count) {
  out = ""; count = 0; n = length(raw)
  for (i = 1; i <= n && count < 200; i++) {
    c = substr(raw, i, 1)
    if (c == "\\") {
      e = substr(raw, i + 1, 1)
      if (e == "n" || e == "r") return out
      if (e == "u") { out = out substr(raw, i, 6); i += 5 } else { out = out substr(raw, i, 2); i++ }
      count++
    } else {
      out = out c
      if (!(c in cont)) count++
    }
  }
  while (i <= n && (substr(raw, i, 1) in cont)) { out = out substr(raw, i, 1); i++ }
  return out
}
function path(raw,    out, i, n, c, e) {
  out = ""; n = length(raw)
  for (i = 1; i <= n; i++) {
    c = substr(raw, i, 1)
    if (c != "\\") { out = out c; continue }
    e = substr(raw, ++i, 1)
    if (e == "\\" || e == "\"" || e == "/") out = out e
    else return ""
  }
  return out
}
BEGIN {
  RS = "\001"
  for (i = 128; i < 192; i++) cont[sprintf("%c", i)] = 1
}
{
  s = $0; n = length(s); p = 1; d = 0
  while (p <= n) {
    c = substr(s, p, 1)
    if (c == "\"") {
      q = p + 1
      while (q <= n) {
        ch = substr(s, q, 1)
        if (ch == "\\") q += 2
        else if (ch == "\"") break
        else q++
      }
      str = substr(s, p + 1, q - p - 1)
      p = q + 1
      if (type[d] == "o" && want[d]) {
        key[d] = str; want[d] = 0
        if (d == 1 && str == "tool_response") break
      } else if (d == 1) top[key[1]] = str
      else if (d == 2 && type[2] == "o" && parent[2] == "tool_input") tool[key[2]] = str
      continue
    }
    if (c == "{" || c == "[") {
      parent[d + 1] = (type[d] == "o") ? key[d] : ""
      d++; type[d] = (c == "{") ? "o" : "a"; want[d] = (c == "{")
    } else if (c == "}" || c == "]") d--
    else if (c == ",") want[d] = (type[d] == "o")
    p++
  }
  where = ("new_cwd" in top) ? top["new_cwd"] : top["cwd"]
  print top["hook_event_name"]
  print top["session_id"]
  print where
  print path(where)
  print top["command_name"]
  print firstline(top["command_args"])
  print top["tool_name"]
  print tool["skill"]
  print firstline(tool["args"])
  print top["notification_type"]
  print top["reason"]
  print top["source"]
}')

{
  IFS= read -r hook
  IFS= read -r session
  IFS= read -r cwd
  IFS= read -r folder
  IFS= read -r command_name
  IFS= read -r command_args
  IFS= read -r tool_name
  IFS= read -r skill
  IFS= read -r skill_args
  IFS= read -r notification
  IFS= read -r reason
  IFS= read -r source
} <<EOF
$parsed
EOF

case $session in
'' | .* | *[!A-Za-z0-9._-]*) exit 0 ;;
esac
project=${CLAUDE_PROJECT_DIR:-$folder}
[ -n "$project" ] || exit 0
common=$(git -C "$project" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
logs="$common/repocop/sessions"
log="$logs/$session.jsonl"

# The repository's own skill called $1, or nothing: only a skill it has is a workflow.
skill_named() {
  name=${1#/}
  case $name in
  '' | -* | *[!a-z0-9-]*) return 1 ;;
  esac
  [ -f "$project/.claude/skills/$name/SKILL.md" ] && printf '%s' "$name"
}

extra=''
case $hook in
SessionStart)
  [ "$source" = compact ] && exit 0 # the same session, carrying on
  event=started
  find "$logs" -type f -name '*.jsonl' -mtime +6 -exec rm -f {} + 2>/dev/null
  ;;
CwdChanged) event=moved ;;
UserPromptSubmit) event=working ;;
UserPromptExpansion)
  workflow=$(skill_named "$command_name") || exit 0
  event=workflow
  extra=",\"workflow\":\"$workflow\",\"argument\":\"$command_args\""
  ;;
PreToolUse)
  case $tool_name in
  Skill)
    workflow=$(skill_named "$skill") || exit 0
    event=workflow
    extra=",\"workflow\":\"$workflow\",\"argument\":\"$skill_args\""
    ;;
  AskUserQuestion)
    event=waiting
    extra=',"waiting_for":"answer"'
    ;;
  *) exit 0 ;;
  esac
  ;;
PermissionRequest)
  event=waiting
  case $tool_name in
  AskUserQuestion) extra=',"waiting_for":"answer"' ;;
  *) extra=",\"waiting_for\":\"permission\",\"tool\":\"$tool_name\"" ;;
  esac
  ;;
Notification)
  event=waiting
  case $notification in
  permission_prompt) extra=',"waiting_for":"permission"' ;;
  elicitation_dialog) extra=',"waiting_for":"answer"' ;;
  *) exit 0 ;;
  esac
  ;;
PostToolUse)
  # Back to work only after something that stopped it; otherwise it was working all along.
  case $(tail -n 1 "$log" 2>/dev/null) in
  *'"event":"waiting"'* | *'"event":"turn-finished"'* | *'"event":"started"'*) event=working ;;
  *) exit 0 ;;
  esac
  ;;
Stop) event=turn-finished ;;
SessionEnd)
  event=closed
  extra=",\"reason\":\"$reason\""
  ;;
*) exit 0 ;;
esac

branch=$(git -C "${folder:-$project}" symbolic-ref --quiet --short HEAD 2>/dev/null |
  sed 's/[\\"]/\\&/g')
[ -n "$branch" ] && branch="\"$branch\"" || branch=null

# The agent's process: the parent of the shell Claude Code ran this hook in, and its start time,
# so a reused process id isn't taken for it. Only where /proc is.
pid=null
pid_start=null
process=$PPID
if [ -r "/proc/$process/stat" ]; then
  hops=0
  while [ "$hops" -lt 3 ]; do
    case $(cat "/proc/$process/comm" 2>/dev/null) in
    sh | dash | bash | ash | zsh | busybox) process=$(awk '{ sub(/.*\) /, ""); print $2 }' "/proc/$process/stat") ;;
    *) break ;;
    esac
    hops=$((hops + 1))
  done
  started=$(awk '{ sub(/.*\) /, ""); print $20 }' "/proc/$process/stat" 2>/dev/null)
  case $started in
  '' | *[!0-9]*) ;;
  *)
    pid=$process
    pid_start="\"$started\""
    ;;
  esac
fi

at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$logs" 2>/dev/null || exit 0
printf '{"v":1,"at":"%s","session":"%s","event":"%s","cwd":"%s","branch":%s,"pid":%s,"pid_start":%s%s}\n' \
  "$at" "$session" "$event" "$cwd" "$branch" "$pid" "$pid_start" "$extra" >>"$log" 2>/dev/null
exit 0
