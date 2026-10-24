---
paths:
  - "tests/**"
  - "repocop/**/*.py"
---

# Testing

How tests run here. Which are worth writing is `.claude/rules/test-policy.md`.

- Write the failing test first, then the code.
- Tests are **hermetic**: use the `host`, `remote_repo` and `primary_checkout` fixtures from `tests/conftest.py`, and never touch the real `~/code`, `~/agent-worktrees`, `~/.claude` or RepoCop's database. The autouse fixture isolates `HOME` and git config.
- Use real `git` on temp repos, never a mock: worktree behaviour is what needs verifying.
- The default suite never calls the real Claude, GitHub or Codex:
  - Claude: the `fake_claude` fixture (`tests/fakes/fake_claude.py`) stands in for the SDK client at `services/claude.py`'s boundary, and a guard fails the real one. Keep the fake in step with the message order verified in `specs/architecture.md` › Claude Code integration. Real-CLI tests get `@pytest.mark.claude` and are skipped unless `REPOCOP_TEST_REAL_CLAUDE=1`.
  - GitHub: `gh` on the tests' `PATH` is `tests/fakes/bin/gh`, which fails without the `fake_gh` fixture. Pushes go to a local bare repository: `github_checkout` gives a checkout whose `origin` is a github.com remote, with an ssh stand-in that runs what git asks of that host on the local repository.
  - Codex: `codex` on the tests' `PATH` is `tests/fakes/bin/codex`, which fails without the `fake_codex` fixture.
- Every invariant in `.claude/rules/safety.md` has a test proving the *refusal*: launching in the primary checkout, path escape, overwriting an existing file, a malicious remote URL, an instruction reaching the wrong session, a push that would need forcing, a review that changes the worktree, and a state-changing request from another site.
- Test routes with FastAPI `TestClient`, asserting on HTML fragments. No browser automation in v0.1.
- Name tests `test_<unit>_<behaviour>`, one behaviour per test.
