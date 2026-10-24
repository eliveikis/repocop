---
paths:
  - "repocop/routes/**"
  - "repocop/templates/**"
  - "repocop/static/**"
---

# Web UI conventions

- Server-rendered Jinja2 templates, with HTMX vendored in `repocop/static/` (no runtime CDN, so it works offline). **No** frontend build step, npm or SPA framework (ADR-005).
- Page-specific JavaScript only where a page genuinely needs it (a diff viewer, a Markdown editor): plain JS in `repocop/static/js/<page>.js` or a library vendored in `repocop/static/vendor/`, loaded only on that page. No global client-side state, and the page still works, degraded, if the script fails.
- Autoescaping stays on. Transcripts, diffs and command output render escaped inside `<pre>`. Never `|safe` on data from a repo, Claude or the user.
- Every state-changing form is a `POST` (or `hx-post`); a `GET` has no side effects.
- Live views (transcript, git status, task status) poll small fragment endpoints with `hx-trigger="every 2s"` and stop once a task reaches a terminal status. WebSockets only if demonstrably simpler.
- Fragments live in `templates/partials/`; full pages extend `base.html`.
- Show errors inline on the page that triggered them, never swallowed.
- Minimal CSS: one hand-written stylesheet and monospace output panes. The operator view matters more than looks.
- Colours are `:root` tokens, each redefined for the dark scheme, used as `var(--token)` and never as raw values. Text meets WCAG AA contrast (4.5:1) on every surface, in both schemes (`tests/test_stylesheet.py`). Links keep their underline, since in the dark scheme colour alone doesn't set them apart.
- Always label human-owned vs. RepoCop-owned paths visibly.
