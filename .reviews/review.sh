#!/bin/sh
# managed by template
# Review this branch with Codex's own review, the way RepoCop runs one, and save it here.
#
#   .reviews/review.sh [base]
#
# The base defaults to the default branch on origin, as last fetched: nothing is fetched. The
# review is read-only and needs no approvals, whatever your own Codex settings say. REVIEW_EFFORT
# sets how hard Codex thinks (default high; blank leaves it to your Codex settings) and
# REVIEW_MODEL the model (default: Codex's own). Codex's progress shows as it works, and the
# review is saved as .reviews/<branch>-<commit>.md, which git ignores, and printed.
set -eu

top=$(git rev-parse --show-toplevel)
cd "$top"

if [ $# -gt 0 ]; then
  base=$1
else
  base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
fi
if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  echo "$base isn't here. Fetch it, or name the base: .reviews/review.sh <base>" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "There are uncommitted changes, which Codex would review too. Commit or stash them first." >&2
  exit 1
fi

branch=$(git branch --show-current)
name=$(printf '%s' "${branch:-detached}" | tr '/' '-')-$(git rev-parse --short HEAD)
out=.reviews/$name.md

set -- review "--base=$base" -c 'sandbox_mode="read-only"' -c 'approval_policy="never"'
effort=${REVIEW_EFFORT-high}
if [ -n "$effort" ]; then
  set -- "$@" -c "model_reasoning_effort=\"$effort\""
fi
if [ -n "${REVIEW_MODEL:-}" ]; then
  set -- "$@" -c "review_model=\"$REVIEW_MODEL\""
fi

partial=$(mktemp "$top/.reviews/.partial.XXXXXX")
trap 'rm -f "$partial"' EXIT
codex "$@" < /dev/null > "$partial"
mv "$partial" "$out"
cat "$out"
echo
echo "Saved as $out"
