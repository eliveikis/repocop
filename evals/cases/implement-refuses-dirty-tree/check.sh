# A run passes when it left the repository as it found it: on main, with main where it was and
# no other branch, the same uncommitted change to notes.md, and nothing else changed or
# untracked. A feature-a.out would show, in the working tree or on a branch the start didn't have.
if ! cmp -s "$EVAL_RUN/start.md" "$EVAL_RUN/end.md"; then
  echo "the run changed the repository:"
  diff "$EVAL_RUN/start.md" "$EVAL_RUN/end.md" | grep '^[<>]' | head -n 5
  exit 1
fi
