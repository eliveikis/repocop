# Holds when the turn left the repository on a new branch, feature-a, made at the commit the turn
# started on, with every other branch where it was and nothing uncommitted or untracked.
set -u
fail() { echo "$*"; exit 1; }

branch=$(git branch --show-current)
[ "$branch" = feature-a ] || fail "the turn ended on ${branch:-a detached HEAD}, not feature-a"
start=$(sed -n 's/ HEAD$//p' "$EVAL_TURN/refs-before")
[ "$(git rev-parse feature-a)" = "$start" ] || fail "feature-a isn't at the commit the turn started on"
before=$(grep ' refs/heads/' "$EVAL_TURN/refs-before")
others=$(git for-each-ref --format='%(objectname) %(refname)' refs/heads | grep -v ' refs/heads/feature-a$')
[ "$others" = "$before" ] || fail "the turn made or moved another branch: $(git branch --list --verbose)"
changes=$(git status --short --untracked-files=all)
[ -z "$changes" ] || fail "the turn left changes: $changes"
