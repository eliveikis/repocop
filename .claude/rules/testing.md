---
paths:
  - "tests/**"
  - "repocop/**/*.py"
---

# Testing

How tests run here. Which are worth writing, and what they may cost, is `.claude/rules/test-policy.md`.

- Write the failing test first, then the code.
- Tests are **hermetic**: use the `host`, `remote_repo` and `primary_checkout` fixtures from `tests/conftest.py`, and never touch the real `~/code`, `~/agent-worktrees`, `~/.claude` or RepoCop's database. The autouse fixture isolates `HOME` and git config.
- Use real `git` on temp repos, never a mock: worktree behaviour is what needs verifying.
- The default suite never calls the real GitHub or Codex:
  - GitHub: `gh` on the tests' `PATH` is `tests/fakes/bin/gh`, which fails without the `fake_gh` fixture. Pushes go to a local bare repository: `github_checkout` gives a checkout whose `origin` is a github.com remote, with an ssh stand-in that runs what git asks of that host on the local repository.
  - Codex, which only the repo template's `.reviews/review.sh` runs: `codex` on the tests' `PATH` is `tests/fakes/bin/codex`, which fails without the `fake_codex` fixture in `tests/test_review_script.py`. Keep the fake in step with the facts verified in `specs/architecture.md` › Branch reviews.
- Every invariant in `.claude/rules/safety.md` has a test proving the *refusal*: a process launched outside the wrappers, a worktree placed in a primary checkout, path escape, overwriting an existing file, a malicious remote URL, a push that would need forcing, and a state-changing request from another site.
- Test routes with FastAPI `TestClient`, asserting on HTML fragments. No browser automation in v0.1.
- Name tests `test_<unit>_<behaviour>`.
- **Time budget:** `make test` runs the suite on every core in under 30 seconds on a developer's machine. Each test has 5 seconds (`timeout` in `pyproject.toml`); one that needs more raises its own with `@pytest.mark.timeout(...)` and says why beside it.
- Tests share nothing but read-only setup, so they run in parallel. Setup that tests only read and that costs git calls is built once per session and copied into each test, as `remote_repo` copies a seed repository.
