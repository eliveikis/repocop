---
depends-on:
  - lean-specs
---
## Requirement

RepoCop's design text sits at the wrong levels. `specs/architecture.md` states how every feature behaves, down to its timeouts and git calls, `templates/README.md` restates the repo template's design, and module docstrings retell the specs. Under the rule `lean-specs` brings, RepoCop's specs are split into area specs, one per broad area of the product, at the level of a user story. The mechanism they held moves to the code that owns it, and the code's docs keep to their own part. An agent that works in one area then reads its design in one place, and how it's built beside the code.

## Acceptance Criteria

1. RepoCop's `specs/architecture.md` holds only what the specs rule says it does, and names each contract between components with where it is stated in full.
2. Each area spec, linked from `specs/index.md`, states its area at the level the specs rule sets. Every rule, constraint, flow and outside contract that `architecture.md` or `templates/README.md` stated is still stated, in a spec or a rule, with its meaning unchanged.
3. Mechanism they stated that the code doesn't make plain is in the docs of the module, script or test that owns it.
4. RepoCop's docstrings and comments keep to their own part: its responsibility, what it guarantees and how. Product design they told that the specs lacked is in the specs.
5. `templates/README.md` keeps only instructions to whoever edits `templates/`.
6. Every reference to a section that moved, as a link or as `<file>` › `<Section>`, points to where it now is: in the specs outside `specs/decisions/`, the rules, the skills, `CLAUDE.md`, `README.md`, code, tests, `repocop.example.yaml`, and the changes in `specs/changes/todo/`.
7. `make check` fails when a Markdown link to a section of another file names no heading there, outside the records and the archived changes.

## Out of scope

- Any change to how RepoCop or the template behaves: this change moves and trims text.
- References in decision records and archived changes, which stay as they were written.
- Archiving decision records: `archive-decision-records`.

## Implementation Notes

- **The split.** This is the expected shape. An area too small for its own spec joins the nearest one:

  | Area spec | From |
  |---|---|
  | `repositories.md` | Repository registry and onboarding; Remote links |
  | `board.md` | Fleet board |
  | `requirements.md` | Requirements and the developer's agent; Requirement storage; A requirement's history; A requirement's review |
  | `sessions.md` | Session events; Session requests |
  | `template-sync.md` | Template sync; Status machine; Pull requests; UI approach's paragraph on a template sync's page |
  | `repo-template.md` | Branch reviews, and the design in `templates/README.md` |
  | `ui.md` | UI approach |

  `architecture.md` keeps the Principle as its goals, Components, the Data model, Coding agents, Configuration and Deployment portability.
- **The level, by example.** From the Fleet board, "stages are read from the repository and GitHub, however the work was done, and nothing on the board acts" stays in `board.md`. "A fixed number of git calls… one walk of the commits the default branch lacks" and the 15-second `gh` timeout go to `board.py` and `github.py`. `board.py`'s docstring keeps what the module computes and how, and drops its copy of the stage table, which `board.md` states. Configuration keeps that only `repocop/config.py` reads config files or the environment, a boundary between components; its search order, refused keys and former name are `config.py`'s.
- **Outside contracts stay in full.** A repository can run an older copy of the template than RepoCop expects, so what the template's hook and scripts and RepoCop exchange is stated in full in its area spec: the session log's format, a request file, and a saved review's header. So are the facts verified on Claude Code and Codex that the hook and the review script rely on.
- **`templates/README.md`.** An instruction to someone editing the folder stays, such as marking a new file's kind, giving a managed file the marker, or adding a settings entry when a skill gains a command. What a kind, the marker or a setting does in a synced repository moves to `repo-template.md`, and how a hook or script does it goes to that file's own header.
- **Pending changes.** `template-section-in-agents-md` and `clean-up-merged-branches` point at sections that move. This change updates those references, and nothing else in them.
- **Checking nothing is lost.** A manual step: for each section of the old text, every rule, constraint, flow and outside contract it stated, its "only", "never", "refuses" and "must", is found in a spec, a rule or the owning code's docs. The pull request lists what was dropped as plain from the code.
