---
paths:
  - "repocop/routes/**"
  - "repocop/templates/**"
  - "repocop/static/**"
---

# Web UI conventions

- Server-rendered Jinja2 templates, with HTMX vendored in `repocop/static/` (no runtime CDN, so it works offline). **No** frontend build step, npm or SPA framework (ADR-005).
- One shared script, `repocop/static/js/shell.js`, loads on every page with HTMX: the quick switcher, keyboard shortcuts, section links and Copy buttons. Beyond it, page-specific JavaScript only where a page genuinely needs it (a diff viewer, a Markdown editor): plain JS in `repocop/static/js/<page>.js` or a library vendored in `repocop/static/vendor/`, loaded only on that page. Every page reads and works without JavaScript, but for the switcher, shortcuts and Copy buttons.
- No client-side state but a per-browser setting in `localStorage`, such as single-key shortcuts turned off, read and written so that a blocked storage only loses the setting.
- Autoescaping stays on. Transcripts, diffs and command output render escaped inside `<pre>`. Never `|safe` on data from a repo, a tool or the user.
- Every state-changing form is a `POST` (or `hx-post`); a `GET` has no side effects.
- A view that must stay current polls a small fragment endpoint with `hx-trigger="every 2s"`, and stops once what it shows can't change. WebSockets only if demonstrably simpler.
- What the shell shows costs each page little, whatever the number of repositories and sessions, since it is on every page and refreshes every 2 s: the database and files, never a process started per repository on each page or refresh (`specs/architecture.md` › UI approach).
- Fragments live in `templates/partials/`; full pages extend `base.html`, the shell: the sidebar, breadcrumbs from the page's `crumbs`, a `toasts` block, the switcher and shortcut dialogs, and the refresh of the page's session lists. Every page but the repository list sets `crumbs`; a long page has section links.
- Show errors inline where they happened, never swallowed. A confirmation (saved, fetched, removed) is a toast in the `toasts` block, which screen readers announce.
- Help that explains a section folds under a **How this works** disclosure. An empty state says what to do next and offers the action. Times go through the `ago` filter: relative, with the exact time on hover.
- One hand-written stylesheet on the system fonts, with no CSS framework or web font, built from the tokens on `:root`: colour, space, type, radius and focus. Buttons, inputs, tables and statuses share one dense style, and a status is a pill that always carries its text. List pages use the window's width. Keyboard focus is always visible, and motion follows the reduced-motion setting.
- Colours are `:root` tokens, each redefined for the dark scheme, used as `var(--token)` and never as raw values. Text meets WCAG AA contrast (4.5:1) on every surface, and control edges and the focus ring 3:1, in both schemes: `tests/test_stylesheet.py` checks every colour token in a pair or lists it as decorative. A link within a sentence keeps its underline, since in the dark scheme colour alone doesn't set it apart. A link that stands alone (navigation, a table cell, a fact's value, a pill, a button) is set apart by where it is, and responds to hover.
- Always label human-owned vs. RepoCop-owned paths visibly.
