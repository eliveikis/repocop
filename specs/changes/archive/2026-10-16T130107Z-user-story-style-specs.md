## Requirement

Developers and agents who write, review or implement a change read its business case first: who needs what, why, and the solution, as a short product story, with acceptance criteria that this party can observe. A change then reads end to end in a minute and can be judged against its purpose. Implementation detail sits apart, in notes written only when the existing patterns don't settle the approach.

## Acceptance Criteria

1. Whoever writes a change finds its format in `.claude/rules/specs.md`, in this repository and in the template:
   - `## Requirement`, a product story (required);
   - `## Acceptance Criteria`, outcomes the story's party can observe (required);
   - `## Out of scope` (optional);
   - `## Implementation Notes` (optional);
   - `## Open questions`, each with a proposed default marked **→**, until settled (optional).
   The sections come in that order. There is no title heading: the file name and the branch name the change.
2. The same rule defines a product story, with one example beside the user story it replaces. A fix's story states the broken outcome, who it affects, and the expected behaviour.
3. `/review-requirement` flags a change that doesn't follow the format: a missing required section, a title heading, a task list instead of a product story, criteria that aren't observable outcomes, implementation detail outside the notes, or notes missing where the existing patterns don't settle the approach. In this repository and in the template.
4. The Lifecycle in `specs/index.md` names the sections where it says how to propose a change, in this repository and in the template.
5. The coordinator writes no title heading in a change it creates, and calls a change by its file name, without `.md`, wherever it names one: its pages, its commit messages and its pull request's title. The New requirement form's name makes the file name, and editing a change edits its whole text.

## Out of scope

- Root design files (`product.md`, `architecture.md`, area specs) and decision records.
- Rewriting existing changes.
- A test of a change's headings: `/review-requirement` is the check.

## Implementation Notes

- A product story follows the same lines as a user story, without its ritual "As a … I want … so that …". It is more clinical: terse, in product terms, with superfluous words cut. Its party needn't be an end user: it can be a developer or agent, or code calling a library's API.
  - User story: "As a user I can edit my settings so that I can configure the game to my liking."
  - Product story: "Users edit their settings to suit their needs or their device. A settings page, reachable from the main menu, provides this."
- Implementation Notes are required only when `/review-requirement` can't settle the approach from the specs, rules and existing code.
- `.claude/rules/specs.md` and `review-requirement` are mirrored into the template, and `tests/test_default_template.py` keeps the copies equal, so repositories get them on their next sync. The template's `specs/index.md` is a starter file, so its Lifecycle change reaches only new repositories.
- The coordinator stops reading a change's first `# ` line as its name, so an existing change's heading is part of its text, shown and edited with the rest. The name is fixed when the change is created, as its slug already is, so the edit form has no name field.
