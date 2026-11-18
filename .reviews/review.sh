#!/bin/sh
# managed by template
# Review this branch with Codex's own review, read-only, and save it here.
#
#   .reviews/review.sh [base] [requirement.md]
#
# In either order. The base defaults to the default branch on origin, as last fetched: nothing is
# fetched. The requirement is the one the branch delivers, by its path from the checkout's top.
# Codex is told only what to review, the commits since the base's merge base and the requirement;
# how to review stays its own. The review is read-only and needs no approvals, whatever your own
# Codex settings say. REVIEW_EFFORT sets how hard Codex thinks (default high; blank leaves it to
# your Codex settings) and REVIEW_MODEL the model (default: Codex's own). Codex's progress shows
# as it works, and the review is saved as .reviews/<branch>-<commit>.md, which git ignores, and
# printed. It refuses, saying why and changing nothing, without Codex installed and signed in,
# without the base, with a requirement that isn't a file committed here, on the base's own
# branch, with uncommitted changes, and with no commits the base lacks.
set -eu

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex isn't installed, or isn't on PATH." >&2
  exit 1
fi

top=$(git rev-parse --show-toplevel)
cd "$top"

base=
requirement=
for arg; do
  case $arg in
  *.md) given=$requirement requirement=$arg ;;
  *) given=$base base=$arg ;;
  esac
  if [ -n "$given" ]; then
    echo "Name one base and one requirement at most: .reviews/review.sh [base] [requirement.md]" >&2
    exit 1
  fi
done
if [ -z "$base" ]; then
  base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
fi
if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  echo "$base isn't here. Fetch it, or name the base: .reviews/review.sh <base>" >&2
  exit 1
fi
if [ -n "$requirement" ] && ! { [ -f "$requirement" ] &&
  git --literal-pathspecs ls-files --error-unmatch -- "$requirement" >/dev/null 2>&1; }; then
  echo "$requirement isn't a file committed here: name it by its path from the checkout's top." >&2
  exit 1
fi
branch=$(git branch --show-current)
# The base's own branch, by its whole name: a remote's branch without the remote, or a local one.
case $(git rev-parse --symbolic-full-name "$base" 2>/dev/null) in
refs/remotes/*/*)
  base_branch=$(git rev-parse --symbolic-full-name "$base")
  base_branch=${base_branch#refs/remotes/}
  base_branch=${base_branch#*/}
  ;;
refs/heads/*)
  base_branch=$(git rev-parse --symbolic-full-name "$base")
  base_branch=${base_branch#refs/heads/}
  ;;
*) base_branch= ;;
esac
if [ -n "$branch" ] && [ "$branch" = "$base_branch" ]; then
  echo "This is $base's own branch: review a branch made from it." >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "There are uncommitted changes, which Codex would review too. Commit or stash them first." >&2
  exit 1
fi
if [ "$(git rev-list --count "$base..HEAD")" -eq 0 ]; then
  echo "This branch has no commits $base lacks, so there's nothing to review." >&2
  exit 1
fi
if ! codex login status </dev/null >/dev/null 2>&1; then
  echo "Codex isn't signed in: run codex login." >&2
  exit 1
fi

name=$(printf '%s' "${branch:-detached}" | tr '/' '-')-$(git rev-parse --short HEAD)
out=.reviews/$name.md

# Codex takes instructions only in place of --base, so they name the base as --base would.
merge_base=$(git merge-base "$base" HEAD)
instructions="Review the code changes against the base branch '$base'. The merge base commit for \
this comparison is $merge_base. Run \`git diff $merge_base\` to inspect the changes relative to \
$base. Provide prioritized, actionable findings."
if [ -n "$requirement" ]; then
  instructions="$instructions The changes deliver the requirement in $requirement."
fi

set -- review -c 'sandbox_mode="read-only"' -c 'approval_policy="never"'
effort=${REVIEW_EFFORT-high}
if [ -n "$effort" ]; then
  set -- "$@" -c "model_reasoning_effort=\"$effort\""
fi
if [ -n "${REVIEW_MODEL:-}" ]; then
  set -- "$@" -c "review_model=\"$REVIEW_MODEL\""
fi

partial=$(mktemp "$top/.reviews/.partial.XXXXXX")
trap 'rm -f "$partial"' EXIT
codex "$@" "$instructions" < /dev/null > "$partial"
mv "$partial" "$out"
cat "$out"
echo
echo "Saved as $out"
