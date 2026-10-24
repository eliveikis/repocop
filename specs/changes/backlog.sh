#!/bin/sh
# managed by template
# Check what each change in todo/ needs delivered first, and draw the backlog in backlog.md beside
# this script: a Mermaid graph of the changes, then the order they can start in. Git ignores
# backlog.md, so draw it again whenever you want to look.
#
#   specs/changes/backlog.sh           check, then draw backlog.md
#   specs/changes/backlog.sh --check   only check
#
# A change lists the changes it needs in its front matter, one name per line:
#
#   ---
#   depends-on:
#     - bulk-import
#   ---
#
# How changes are named, and which are delivered: .claude/rules/specs.md. When a name matches no
# change or more than one, a change needs itself, changes form a cycle, or a depends-on can't be
# read, each problem is printed and nothing is drawn. Exits 0 when all is well, 1 on a problem,
# 2 on a wrong option. Needs only sh and awk.
set -eu

LC_ALL=C
export LC_ALL

usage() {
  echo "usage: $0 [--check]" >&2
  exit 2
}

check=
case $# in
  0) ;;
  1) if [ "$1" = --check ]; then check=1; else usage; fi ;;
  *) usage ;;
esac

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

# The changes in todo/, read for their front matter, then the delivered ones, by name only.
set --
for file in "$here"/todo/*.md; do
  if [ -f "$file" ]; then set -- "$@" "$file"; fi
done
set -- "$@" :archive:
for file in "$here"/archive/*.md; do
  if [ -f "$file" ]; then set -- "$@" "$file"; fi
done

if [ -n "$check" ]; then
  out=/dev/null
else
  out=$here/.backlog.md.$$
  trap 'rm -f "$out"' EXIT
fi

awk '
function name_of(path,    s) {
  s = path
  sub(/^.*\//, "", s)
  sub(/\.md$/, "", s)
  sub(/^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z-/, "", s)
  sub(/^req-[0-9][0-9]*-/, "", s)
  return s
}

function problem(names, text) {
  problems[++np] = names ": " text
}

function unreadable(text) {
  problem(nm[cur], text)
  unread[cur] = 1
  state = "done"
}

function finish() {
  if (cur != "" && state == "front") unreadable("its front matter has no closing ---")
}

function visit(root, i,    k, j) {
  for (k = 1; k <= ne[i]; k++) {
    j = need[i, k]
    if (!((root, j) in reach)) {
      reach[root, j] = 1
      visit(root, j)
    }
  }
}

function depth(i,    k, d, best) {
  if (i in level) return level[i]
  best = 0
  for (k = 1; k <= ne[i]; k++) {
    d = depth(need[i, k]) + 1
    if (d > best) best = d
  }
  level[i] = best
  return best
}

BEGIN {
  archive = 0
  for (a = 1; a < ARGC; a++) {
    if (ARGV[a] == ":archive:") archive = 1
    else if (archive) delivered[name_of(ARGV[a])]++
    else paths[++n] = ARGV[a]
    if (archive) ARGV[a] = ""
  }
  for (i = 2; i <= n; i++) {
    p = paths[i]
    for (j = i - 1; j >= 1 && paths[j] > p; j--) paths[j + 1] = paths[j]
    paths[j + 1] = p
  }
  for (i = 1; i <= n; i++) {
    at[paths[i]] = i
    file[i] = paths[i]
    sub(/^.*\//, "", file[i])
    nm[i] = name_of(paths[i])
    count[nm[i]]++
    byname[nm[i]] = i
  }
  cur = ""
}

FNR == 1 {
  finish()
  cur = at[FILENAME]
  state = "body"
  listing = 0
  seen = 0
}

{
  line = $0
  sub(/\r$/, "", line)
  if (FNR == 1) {
    if (line == "---") state = "front"
    next
  }
  if (state != "front") next
  if (line == "---") {
    state = "done"
    next
  }
  if (listing) {
    if (line ~ /^[ \t]*$/ || line ~ /^[ \t]*#/) next
    if (line ~ /^[ \t]*-[ \t]+[^ \t]+[ \t]*$/) {
      d = line
      sub(/^[ \t]*-[ \t]+/, "", d)
      sub(/[ \t]+$/, "", d)
      if (!((cur, d) in listed)) {
        listed[cur, d] = 1
        dep[cur, ++nd[cur]] = d
      }
      next
    }
    # Only the next key, unindented, ends the list.
    if (line ~ /^[ \t-]/ || line !~ /:/) {
      unreadable("has a line under depends-on that is not \"- <name>\": \"" line "\"")
      next
    }
    listing = 0
  }
  if (line ~ /^depends-on:[ \t]*$/) {
    if (seen) unreadable("has depends-on twice")
    else {
      seen = 1
      listing = 1
    }
  } else if (line ~ /^depends-on:/) {
    unreadable("lists its depends-on on one line; put each name on a line of its own, after \"- \"")
  }
}

END {
  finish()
  for (i = 1; i <= n; i++) {
    if (unread[i]) continue
    for (k = 1; k <= nd[i]; k++) {
      d = dep[i, k]
      m = count[d] + delivered[d]
      if (d == nm[i]) problem(nm[i], "needs itself")
      else if (m == 0) problem(nm[i], "needs \"" d "\", which matches no change")
      else if (m > 1) problem(nm[i], "needs \"" d "\", which matches more than one change")
      else if (count[d] == 1) need[i, ++ne[i]] = byname[d]
    }
  }
  for (i = 1; i <= n; i++) visit(i, i)
  for (i = 1; i <= n; i++) {
    if (!((i, i) in reach) || (i in cyclic)) continue
    names = ""
    for (j = 1; j <= n; j++) {
      if ((i, j) in reach && (j, i) in reach) {
        cyclic[j] = 1
        names = names (names == "" ? "" : ", ") nm[j]
      }
    }
    problem(names, "depend on one another in a cycle")
  }
  if (np) {
    for (p = 1; p <= np; p++) print problems[p] | "cat 1>&2"
    close("cat 1>&2")
    exit 1
  }

  print "<!-- Drawn by backlog.sh from the depends-on of each change in todo/. Draw it again rather than edit it. -->"
  print ""
  print "# Backlog"
  print ""
  if (n == 0) {
    print "Nothing in todo/."
    exit 0
  }
  print "```mermaid"
  print "flowchart LR"
  for (i = 1; i <= n; i++) {
    label = nm[i]
    gsub(/"/, "#quot;", label)
    print "    c" i "[\"" label "\"]"
  }
  for (i = 1; i <= n; i++) {
    for (k = 1; k <= ne[i]; k++) print "    c" need[i, k] " --> c" i
  }
  print "```"
  top = 0
  for (i = 1; i <= n; i++) {
    if (depth(i) > top) top = depth(i)
  }
  for (l = 0; l <= top; l++) {
    print ""
    if (l == 0) print "## Can start now"
    else print "## After " l " more"
    print ""
    for (i = 1; i <= n; i++) {
      if (level[i] != l) continue
      link = file[i]
      gsub(/ /, "%20", link)
      print "- [" nm[i] "](todo/" link ")"
    }
  }
}
' "$@" < /dev/null > "$out"

if [ -z "$check" ]; then mv -- "$out" "$here/backlog.md"; fi
