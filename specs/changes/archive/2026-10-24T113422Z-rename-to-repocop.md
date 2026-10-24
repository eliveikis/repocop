## Requirement

`specs/product.md` names the product RepoCop, a fleet manager for agentic repositories. Everything else still calls it the coordinator: the package, the command, the configuration, the pages, the rules and the repo template. The repository and its folder are called `orchestrator`. "Coordinator" is too generic to search for, and three names for one product confuse anyone who meets it.

The product calls itself RepoCop everywhere it names itself. A developer's existing configuration and database carry over by a step the developer takes, and are never silently left behind.

## Acceptance Criteria

1. `uv run repocop` starts the app, and no package or command named `coordinator` remains.
2. Settings come from `REPOCOP_<KEY>` variables and from the first of `$REPOCOP_CONFIG`, `./repocop.yaml` and `$XDG_CONFIG_HOME/repocop/config.yaml`. The default data folder is `$XDG_DATA_HOME/repocop`, holding `repocop.db` and `logs/`.
3. The app refuses to start, as for any invalid configuration (exit code 2), when something under the old name would otherwise be ignored without a word, and says how to carry it over:
   - a config file at an old location, with none at the new ones: the command that moves it
   - the default data folder under the old name, with no new one and no `database_path` or `logs_dir` set: the command that moves it
   - a `COORDINATOR_` environment variable: the variable that replaces it

   Afterwards the files under the old names are unchanged.
4. A database from before the rename opens, and a task that failed because the app restarted shows the new restart reason (open question 2).
5. The pages, `make run`, `make doctor`, the README and the example configuration say RepoCop.
6. `CLAUDE.md`, `AGENTS.md`, `REVIEW.md`, `specs/architecture.md`, `specs/index.md`, the rules, the skills and the repo template call the product RepoCop, including where it names a role ("a RepoCop worktree"). An onboarded repository gets the template's renamed files through template sync.
7. `make check` fails when "coordinator" appears in a tracked file other than a decision record, a change, or the checks of criterion 3.

## Out of scope

- Renaming the GitHub repository, the local folder and Claude Code's project folder, which the developer does by hand (Implementation Notes).
- Reading configuration or data from the old locations as a fallback.
- Editing decision records or changes, which keep the old name.
- Publishing to PyPI, building executables, or making the repository public.
- Changing what the product does.

## Implementation Notes

- The package, command and distribution in `pyproject.toml` are `repocop`, and its description is the one-liner in `specs/product.md`'s Vision, whose sentence saying the rest still calls it the coordinator goes. `CoordinatorError` becomes `RepoCopError`, and the tests' `COORDINATOR_TEST_REAL_CLAUDE` becomes `REPOCOP_TEST_REAL_CLAUDE`.
- The old-name checks live in `coordinator/config.py`, the only module that reads config files or the environment.
- The repo template's files change together with this repository's copies (`tests/test_default_template.py`).
- A decision record covers the name and the term "fleet manager for agentic repositories". "Control plane" was too vague. Fleet management is the established name for keeping many members on one baseline while showing each one's state. RepoCop is short, easy to spell in any language, and unused by any live tool in this space. It rejects Harbormaster, Concertmaster, RepoRegulator, RepoControl and RepoWrangler, while Muster, Regatta and RepoRails were already taken by agent tools. The record also says why nothing moves the developer's files on its own.
- After the merge, the developer:
  1. moves the config file and the data folder as the refusal messages say
  2. renames the GitHub repository to `repocop`, and points `origin` at its new URL
  3. renames the local folder, moves Claude Code's project folder under `~/.claude/projects/` (named after the checkout's path) so its memory follows, and accepts Claude Code's trust prompt again, since trust is looked up by the checkout's path
  4. if this repository is registered in its own RepoCop, adds it again under its new name: the old entry shows as `missing`, with its history

## Open questions

1. **Old configuration and data.** **→** Refuse to start and name the command that moves them. RepoCop never moves a developer's files on its own, and nothing is lost. The alternatives are moving them automatically on first start, which is convenient but moves files without asking, or reading the old locations as a fallback, which keeps two names working indefinitely.
2. **The stored restart reason.** Tasks stopped by a restart are stored with the reason `coordinator_restarted`. **→** `app_restarted`, which doesn't name the product, so a later rename leaves stored data alone, with a forward-only migration rewriting the rows that hold the old value. The alternative, `repocop_restarted`, follows today's pattern.
