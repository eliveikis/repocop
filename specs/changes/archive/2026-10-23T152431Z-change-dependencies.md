## Requirement

Changes in `specs/changes/todo/` often need others delivered first, and whoever orders the backlog can't see which. A dependency written in a change's prose can't be checked, and goes stale once the dependency is delivered.

Each change lists the changes it needs in its front matter. The coordinator's requirements section shows what each change is blocked by and what can start now. Outside it, one script with nothing to install checks the lists and draws the backlog as a graph to open in the editor.

## Acceptance Criteria

1. A change lists the changes that must be delivered before it in front matter, one per line under `depends-on:`, each by its name: its file name without `.md`, any archive timestamp and any `req-<id>-` prefix. A change that needs none has no `depends-on`.
2. A dependency is delivered once its change is in `specs/changes/archive/`. The change that needs it is left as it is.
3. A requirement's page shows **Blocked by**, each change it needs with the delivered ones marked done, and **Blocks**, each undelivered change that needs it. Each links to its page when it has one.
4. A repository's requirements section groups every change in its requirements folder, tracked or not, by level: **Can start now** (every dependency delivered), then **After 1 more**, **After 2 more** and so on, by the longest chain of undelivered changes it waits on, then the delivered ones. Each keeps the actions it has today. A **Ready** filter shows only the changes that can start now.
5. A problem in the dependencies, as listed in 7, shows as an error in that section naming the change and the problem. The changes it involves are listed apart, and the rest are grouped as usual.
6. `specs/changes/backlog.sh` writes `specs/changes/backlog.md`: a Mermaid flowchart of every change in `todo/`, with an arrow from each undelivered dependency to the change that needs it, followed by the changes that can start now. Git ignores the file. The script needs only `sh`, `awk`, `tsort` and `git`, and works from any folder of the repository.
7. The script refuses, exiting non-zero, naming the change and the problem, and writing nothing: a name that matches no change or more than one, a change that depends on itself, a cycle (naming its changes), and a `depends-on` it can't read. `backlog.sh --check` makes the same checks and writes nothing, and this repository's `make check` fails on them.
8. Repositories get the script, its ignore file and the convention through template sync.

## Out of scope

- Enforcing dependencies, such as warning before a task starts on a change that is blocked.
- A drawn graph in the coordinator.
- Relations other than "delivered first", such as changes that overlap or replace one another: those are merged or dropped.
- Rewriting the prose `## Depends on` sections of existing changes.

## Implementation Notes

- The coordinator never runs a repository's scripts, so it reads the front matter itself. This repository's tests run it and `backlog.sh` on the same changes, and expect the same levels and the same refusals.
- A dependency's name is only compared with the folder's file names, never used to build a path.
- `.claude/rules/specs.md` describes `depends-on` and the script. A decision record covers declaring dependencies in each change, and drawing the graph on request instead of keeping one in a file.
- `tsort` gives the order and finds cycles. The script and `specs/changes/.gitignore` are managed template files, so they carry the marker, and this repository mirrors them.

## Open questions

1. **Where the graph lives.** **→** An ignored `specs/changes/backlog.md`, drawn on request. Dependencies are often edited through the coordinator, which commits a requirement file alone (ADR-004), so a committed graph would be out of date after most edits, and a check that it's current would fail unrelated branches. `specs/index.md` is also a starter file, which sync never updates. The alternative, a committed graph, shows on GitHub.
2. **Where the script lives.** **→** `specs/changes/backlog.sh`, beside the folders it reads and the file it writes. The `complete-change` skill's folder would tie it to archiving, but adding or editing a change changes the graph too.
