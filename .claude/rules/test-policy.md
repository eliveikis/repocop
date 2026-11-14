<!-- managed by template -->
# Test policy

Which tests are worth writing, and what they may cost, wherever a repository has automated tests. Its own testing rule, `.claude/rules/testing.md`, names its surfaces, critical areas, tools and time budget.

- **Black-box by default:** test a part through its real surface, not its internals, so tests survive refactoring: a server over HTTP against its real database, a client from its real entry point against a fake server, end-to-end suites against the real system, the boundary between components.
- **Below the surface only for what's critical and intricate,** where a failure would be silent or costly: determinism, core domain rules, verification, refusals on safety and auth paths, money. Where a rule's cases can be stated as a property, one property-based test covers them better than a table of examples.
- **Not tested:** layout and looks (checked by hand, with captures), thin glue, wiring, dev-tool conveniences, and numbers meant to be tuned.
- **A new test must be able to fail where no other would.** Before adding one, find the test that already drives that surface, and add a case or an assertion to it instead.
- **Assert all of an action's outcomes in one test,** rather than repeating its setup to check one at a time. Where setup is costly, one test may take the steps of one workflow in turn.
- **Prove a bug fix with a check that fails without it.** Keep it as a test only where this policy would test that behaviour, as a case in the test that already drives it where there is one.
- **Every test costs time on every run.** Build costly setup that tests only read once per run, keep tests independent so they can run in parallel, and keep the suite within the repository's time budget. A test much slower than its peers says why.
- **Delete a test** that pins implementation details once it gets in the way, or that can no longer fail where no other would.
