#!/bin/sh
# managed by template
# Archive a change: move it into the archive/ folder beside its folder, its name stamped with the
# UTC date and time, then list the files that still mention its old path.
#
#   .claude/skills/complete-change/archive.sh specs/changes/todo/<file>.md
#
# Prints the new path on the first line, then each mention as `file:line:text`. The move is
# staged with `git mv`; nothing is committed.
set -eu

if [ $# -ne 1 ]; then
  echo "usage: $0 <path of the change>" >&2
  exit 2
fi
cd "$(git rev-parse --show-toplevel)"
change=$1
if [ ! -f "$change" ]; then
  echo "$change isn't a file in $(pwd)" >&2
  exit 1
fi
if ! git ls-files --error-unmatch -- "$change" >/dev/null 2>&1; then
  echo "$change isn't committed, so git can't move it" >&2
  exit 1
fi

folder=$(dirname "$change")
name=$(basename "$change")
archive=$(dirname "$folder")/archive
target=$archive/$(date -u +%Y-%m-%dT%H%M%SZ)-$name

mkdir -p "$archive"
git mv -- "$change" "$target"
echo "$target"
git grep -n -F -e "$(basename "$folder")/$name" -- . ":(exclude)$target" || true
