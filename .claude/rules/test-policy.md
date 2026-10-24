<!-- managed by template -->
# Test policy

Which tests are worth writing, wherever a repository has automated tests. Its own testing rule or `CLAUDE.md` names its surfaces, critical areas and tools.

- **Black-box by default:** test a part through its real surface, not its internals: a server over HTTP against its real database, a client from its real entry point against a fake server, end-to-end suites against the real system, the boundary between components.
- **Unit tests only for what's critical and intricate,** where a failure would be silent or costly: determinism, core domain rules, verification, refusals on safety and auth paths, money.
- **Not tested:** layout and looks (checked by hand, with captures), thin glue, wiring, dev-tool conveniences, and numbers meant to be tuned.
- **A bug fixed in a tested layer gets a test** that would have caught it.
- **Extend an existing test** when the setup is shared, rather than adding another.
- **A slow test needs a reason.**
- **Delete a test that pins implementation details** once it gets in the way.
