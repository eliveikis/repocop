#!/bin/sh
# managed by template
# Hook on Claude Code's session events: records what this session does, one JSON line per event in
# RepoCop's session log format, in <git common dir>/repocop/sessions/<session id>.jsonl, a folder
# every worktree of the repository shares and no commit holds. A line names the session, the
# time, the folder and branch it is in, the agent's process and its inbox socket; beyond those it
# holds only a workflow's name and the first line of its argument, the tool a permission wait is
# for, or why the session closed. Never a prompt, a command or what the agent said. It runs async
# and always exits 0, so it never delays or fails the session. Hooks run side by side and finish
# in any order, so a line's time is when its hook started, to the nanosecond where `date` can say:
# that, not where it lands in the log, orders it. A session's start removes the logs and requests
# that have gone a week untouched, and its end the request still waiting for it.
#
# With `deliver`, on Stop, it instead hands this session the request waiting for it in
# <git common dir>/repocop/inbox/<session id>.json, if there is one, so it carries on with it at
# once: a workflow and the requirement to run it on, left there by RepoCop's requirement page on
# the developer's click. The request is taken once, by renaming it, and checked first: the
# workflow must be a skill committed in the session's checkout, and the requirement a file there,
# and nothing else in it is passed on. A taken request is recorded as delivered beside it.
#
# Needs only sh, awk and git.
at=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
case $at in
*[!0-9TZ:.-]*) at=$(date -u +%Y-%m-%dT%H:%M:%SZ) ;; # a date without nanoseconds
esac
LC_ALL=C
export LC_ALL

input=$(cat)

# fields KEY...: the value of each KEY in the JSON object on standard input, one per line, as JSON
# holds it, escapes and all, or an empty line when it has none. A KEY names a top-level string, or
# one in its tool_input as `tool_input.NAME`. Before a KEY, `first:` keeps only its first line, at
# most 200 characters, and `path:` decodes it into a path, or nothing when it holds an escape a
# path can't be read from. A small JSON scanner, which stops at tool_response.
fields() {
  awk -v keys="$*" '
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
      } else if (d == 1) value[key[1]] = str
      else if (d == 2 && type[2] == "o" && parent[2] == "tool_input") value["tool_input." key[2]] = str
      continue
    }
    if (c == "{" || c == "[") {
      parent[d + 1] = (type[d] == "o") ? key[d] : ""
      d++; type[d] = (c == "{") ? "o" : "a"; want[d] = (c == "{")
    } else if (c == "}" || c == "]") d--
    else if (c == ",") want[d] = (type[d] == "o")
    p++
  }
}
END {
  count = split(keys, wanted, " ")
  for (i = 1; i <= count; i++) {
    name = wanted[i]
    if (sub(/^first:/, "", name)) print firstline(value[name])
    else if (sub(/^path:/, "", name)) print path(value[name])
    else print value[name]
  }
}'
}

{
  IFS= read -r hook
  IFS= read -r session
  IFS= read -r cwd
  IFS= read -r folder
  IFS= read -r moved_to
  IFS= read -r moved_folder
  IFS= read -r command_name
  IFS= read -r command_args
  IFS= read -r tool_name
  IFS= read -r skill
  IFS= read -r skill_args
  IFS= read -r notification
  IFS= read -r reason
  IFS= read -r source
} <<EOF
$(printf '%s' "$input" | fields hook_event_name session_id cwd path:cwd new_cwd path:new_cwd \
  command_name first:command_args tool_name tool_input.skill first:tool_input.args \
  notification_type reason source)
EOF
if [ -n "$moved_to" ]; then
  cwd=$moved_to
  folder=$moved_folder
fi

case $session in
'' | .* | *[!A-Za-z0-9._-]*) exit 0 ;;
esac
project=${CLAUDE_PROJECT_DIR:-$folder}
[ -n "$project" ] || exit 0
common=$(git -C "$project" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
logs="$common/repocop/sessions"
log="$logs/$session.jsonl"
inbox="$common/repocop/inbox"

# The request waiting for this session, handed to it: printed as Stop's decision to carry on.
deliver() {
  [ "$hook" = Stop ] && [ -f "$inbox/$session.json" ] || return 0
  taking="$inbox/$session.taking.$$"
  mv "$inbox/$session.json" "$taking" 2>/dev/null || return 0 # another took it
  {
    IFS= read -r id
    IFS= read -r workflow
    IFS= read -r requirement
    IFS= read -r requirement_path
  } <<EOF
$(fields id workflow requirement path:requirement <"$taking")
EOF
  rm -f "$taking"
  case $id in
  '' | *[!A-Za-z0-9-]*) return 0 ;;
  esac
  case $workflow in
  '' | -* | *[!a-z0-9-]*) return 0 ;;
  esac
  # The path itself, decoded: none when it holds a line break or another escape a path can't.
  case $requirement_path in
  *.md) ;;
  *) return 0 ;;
  esac
  case $requirement_path in
  /* | ../* | */../* | */.. | *\\* | *'`'*) return 0 ;; # outside, or a mark that ends the line
  esac
  [ -f "$project/$requirement_path" ] || return 0
  git -C "$project" cat-file -e "HEAD:.claude/skills/$workflow/SKILL.md" 2>/dev/null || return 0
  printf '{"v":1,"id":"%s","workflow":"%s","requirement":"%s","at":"%s"}\n' \
    "$id" "$workflow" "$requirement" "$at" >"$inbox/$session.delivered.json"
  printf '{"decision":"block","reason":"The developer asks, from RepoCop: run the `%s` skill with the argument `%s`."}\n' \
    "$workflow" "$requirement"
}
if [ "${1-}" = deliver ]; then
  deliver
  exit 0
fi

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
  find "$logs" "$inbox" -type f -mtime +6 -exec rm -f {} + 2>/dev/null
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
PostToolUse) event=working ;; # back at work, whatever the log says yet: a wait may land later
Stop) event=turn-finished ;;
SessionEnd)
  event=closed
  extra=",\"reason\":\"$reason\""
  rm -f "$inbox/$session.json"
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

# Where other processes reach this session's agent, as Claude Code tells its hooks.
socket=$(printf '%s' "${CLAUDE_CODE_MESSAGING_SOCKET-}" | sed 's/[\\"]/\\&/g')
[ -n "$socket" ] && socket="\"$socket\"" || socket=null

mkdir -p "$logs" 2>/dev/null || exit 0
printf '{"v":1,"at":"%s","session":"%s","event":"%s","cwd":"%s","branch":%s,"pid":%s,"pid_start":%s,"socket":%s%s}\n' \
  "$at" "$session" "$event" "$cwd" "$branch" "$pid" "$pid_start" "$socket" "$extra" >>"$log" 2>/dev/null
exit 0
