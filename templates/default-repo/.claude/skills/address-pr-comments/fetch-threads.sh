#!/usr/bin/env bash
# managed by template
# Print a pull request's open review feedback as compact Markdown, for /address-pr-comments.
# Usage: fetch-threads.sh [pr-number]   (default: the PR for the current branch)
#
# One read-only GraphQL call through the gh CLI, printed to stdout (nothing is written to disk).
# - Resolved threads and minimized comments are dropped.
# - Outdated unresolved threads are listed in brief, because the code under them has changed.
# - Bot conversation comments (CI, coverage) are dropped. Bot review threads are kept.
# - Each list is capped at 100 items, and the output says so when a cap is hit.
set -euo pipefail

command -v gh >/dev/null || { echo "gh CLI not found: install it and run 'gh auth login'." >&2; exit 1; }

pr="${1:-$(gh pr view --json number --jq .number)}"
[[ "$pr" =~ ^[0-9]+$ ]] || { echo "Usage: $0 [pr-number]" >&2; exit 2; }

query='
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number title url headRefName
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          isResolved isOutdated path line startLine originalLine
          comments(first: 50) { nodes { author { login } body diffHunk url isMinimized } }
        }
      }
      reviews(last: 100) {
        pageInfo { hasPreviousPage }
        nodes { author { login } state body isMinimized }
      }
      comments(last: 100) {
        pageInfo { hasPreviousPage }
        nodes { author { login __typename } body url isMinimized }
      }
    }
  }
}'

format='
def who: .author.login // "ghost";
def indent: gsub("\n"; "\n  ");
def excerpt: split("\n") | .[-8:] | join("\n");
def firstline: split("\n") | .[0] | .[:160];
def loc: .path + ((.line // .originalLine) as $l
  | if $l == null then ""
    elif .startLine != null and .startLine != $l then ":\(.startLine)-\($l)"
    else ":\($l)" end);
def capped($conn; $what):
  if ($conn.pageInfo | .hasNextPage or .hasPreviousPage) then "", "_More than 100 \($what): only 100 shown._" else empty end;

.data.repository.pullRequest as $pr
| [ $pr.reviewThreads.nodes[]
    | select(.isResolved | not)
    | .comments = [ .comments.nodes[] | select(.isMinimized | not) ]
    | select(.comments | length > 0) ] as $open
| [ $open[] | select(.isOutdated | not) ] as $current
| [ $open[] | select(.isOutdated) ] as $outdated
| [ $pr.reviews.nodes[]
    | select(.body != "" and (.isMinimized | not) and .state != "PENDING" and .state != "DISMISSED") ] as $reviews
| [ $pr.comments.nodes[] | select((.isMinimized | not) and .author.__typename != "Bot") ] as $talk
| "# PR #\($pr.number): \($pr.title)",
  "Branch: `\($pr.headRefName)` · \($pr.url)",
  "",
  "## Unresolved threads (\($current | length))",
  ( $current[]
    | "", "### \(loc)", .comments[0].url,
      ( .comments[0].diffHunk // "" | if . == "" then empty else "```diff", excerpt, "```" end ),
      ( .comments[] | "- **\(who):** \(.body | indent)" ) ),
  capped($pr.reviewThreads; "review threads"),
  "",
  "## Outdated unresolved threads (\($outdated | length))",
  ( if ($outdated | length) > 0 then "_The code under these changed after the comment. Check whether each still applies._" else empty end ),
  ( $outdated[]
    | "- `\(loc)` **\(.comments[0] | who):** \(.comments[0].body | firstline) (\(.comments | length) comments) \(.comments[0].url)" ),
  "",
  "## Review summaries (\($reviews | length))",
  ( $reviews[] | "- **\(who)** (\(.state)): \(.body | indent)" ),
  capped($pr.reviews; "reviews"),
  "",
  "## Conversation comments (\($talk | length))",
  ( if ($talk | length) > 0 then "_These cannot be resolved, so earlier ones may already be addressed._" else empty end ),
  ( $talk[] | "- **\(who):** \(.body | indent)" ),
  capped($pr.comments; "conversation comments")
'

gh api graphql \
  -F owner='{owner}' -F name='{repo}' -F number="$pr" \
  -f query="$query" \
  --jq "$format"
