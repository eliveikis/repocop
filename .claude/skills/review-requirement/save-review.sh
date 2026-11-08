#!/bin/sh
# managed by template
# Save a requirement's review in <git common dir>/repocop/reviews/<requirement's file name>: on
# this machine, out of every commit, shared by every worktree of the repository, replacing the
# requirement's last saved review. A header records the verdict, how many blocking questions the
# review asks, the SHA-256 of the requirement's file as reviewed, so a later edit shows, and when
# it was saved; the review, read from standard input, follows it.
#
#   .claude/skills/review-requirement/save-review.sh <requirement path> <verdict> <blocking questions> <review.md
#
# The path is relative to the checkout's top. The verdict is yes, yes-with-assumptions or no.
# Prints the saved file's path. Exits 2 on a wrong argument, 1 when the review can't be saved.
set -eu

fail() {
  echo "ERROR: $1" >&2
  exit "${2:-1}"
}

[ $# -eq 3 ] || fail "usage: $0 <requirement path> <verdict> <blocking questions> <review.md" 2
requirement=$1 verdict=$2 blocking=$3
case $verdict in
yes | yes-with-assumptions | no) ;;
*) fail "the verdict is yes, yes-with-assumptions or no, not '$verdict'" 2 ;;
esac
case $blocking in
'' | *[!0-9]*) fail "the blocking questions are a count, not '$blocking'" 2 ;;
esac
newline='
'
case $requirement in
'' | /* | -* | *"$newline"*) fail "the requirement is a path relative to the checkout's top" 2 ;;
esac
case /$requirement/ in
*/../* | */./*) fail "the requirement's path has no '.' or '..' in it" 2 ;;
esac
case $requirement in
*.md) ;;
*) fail "the requirement is a Markdown file" 2 ;;
esac
if printf '%s' "$requirement" | LC_ALL=C grep -q '[[:cntrl:]]'; then
  fail "the requirement's path has no control characters" 2
fi

top=$(git rev-parse --show-toplevel) || fail "not in a git checkout"
cd "$top"
top=$(pwd -P)
[ -f "$requirement" ] && [ ! -L "$requirement" ] || fail "$requirement isn't a file in $top"
real=$(realpath -- "$requirement")
case $real in
"$top"/*) ;;
*) fail "$requirement leads outside $top" ;;
esac

common=$(git rev-parse --path-format=absolute --git-common-dir) || fail "no git folder"
for folder in "$common/repocop" "$common/repocop/reviews"; do
  [ ! -L "$folder" ] || fail "$folder is a link"
  mkdir -p -- "$folder"
done
reviews=$common/repocop/reviews

if command -v sha256sum >/dev/null 2>&1; then
  sha=$(sha256sum <"$requirement" | cut -d' ' -f1)
elif command -v shasum >/dev/null 2>&1; then
  sha=$(shasum -a 256 <"$requirement" | cut -d' ' -f1)
else
  fail "neither sha256sum nor shasum is installed"
fi
at=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
case $at in
*[!0-9TZ:.-]*) at=$(date -u +%Y-%m-%dT%H:%M:%SZ) ;; # a date without nanoseconds
esac

draft=$(mktemp "$reviews/.saving.XXXXXX")
trap 'rm -f -- "$draft"' EXIT
printf -- '---\nv: 1\nrequirement: %s\nverdict: %s\nblocking: %s\nsha256: %s\nat: %s\n---\n' \
  "$requirement" "$verdict" "$blocking" "$sha" "$at" >"$draft"
header=$(wc -c <"$draft")
cat >>"$draft"
[ "$(wc -c <"$draft")" -gt "$header" ] || fail "no review on standard input"
saved=$reviews/$(basename -- "$requirement")
mv -f -- "$draft" "$saved"
echo "$saved"
