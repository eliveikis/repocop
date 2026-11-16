# Passes when the repository is on feature-b; feature-b is one commit ahead of main, a commit
# that adds feature-b.out, and nothing is uncommitted; no branch has a feature-a.out; main and
# feature-a are where turn 1 left them, and no other branch was made; and both requirement files
# are unchanged.
set -u
fail() { echo "$*"; exit 1; }

branch=$(git branch --show-current)
[ "$branch" = feature-b ] || fail "the run ended on ${branch:-a detached HEAD}, not feature-b"
git merge-base --is-ancestor main feature-b && [ "$(git rev-list --count main..feature-b)" = 1 ] \
  || fail "feature-b isn't one commit ahead of main: $(git log --oneline main..feature-b | wc -l) commits"
git diff --name-only --diff-filter=A main feature-b | grep -qx 'feature-b\.out' \
  || fail "feature-b's commit doesn't add feature-b.out"
changes=$(git status --short --untracked-files=no)
[ -z "$changes" ] || fail "changes are left uncommitted: $changes"
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  if git cat-file -e "$b:feature-a.out" 2>/dev/null; then fail "$b has a feature-a.out"; fi
done
left=$(grep -E ' refs/heads/(main|feature-a)$' "$EVAL_RUN/turn-1/refs-after")
now=$(git for-each-ref --format='%(objectname) %(refname)' refs/heads/main refs/heads/feature-a)
[ "$now" = "$left" ] || fail "main or feature-a moved after turn 1"
branches=$(git for-each-ref --format='%(refname:short)' refs/heads | tr '\n' ' ')
[ "$branches" = "feature-a feature-b main " ] || fail "the branches are $branches"
start=$(sed -n 's/ HEAD$//p' "$EVAL_RUN/turn-1/refs-before")
git diff --quiet "$start" -- specs/changes/todo/feature-a.md specs/changes/todo/feature-b.md \
  || fail "a requirement file was changed"
