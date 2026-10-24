## Requirement

An operator watching agents across several repositories needs to see what's running and get to any repository, requirement or task quickly. Today each page is a narrow column with a brand link and a back link. Nothing shows what's running elsewhere, everything is reached by clicking down from the repository list, and long help paragraphs and browser-default controls make the pages dated and hard to scan.

Every page gets a sidebar, breadcrumbs, a quick switcher and keyboard shortcuts, long pages get section links, and the stylesheet is refreshed for a modern, dense look in light and dark.

## Acceptance Criteria

1. **Sidebar.** Every page has a sidebar listing the repositories, and the active tasks across all of them (queued, running or waiting for the user), each with its status and repository. Each links to its page. The list stays current while tasks are active, and the sidebar folds behind a menu button in a narrow window.
2. **Breadcrumbs.** Every page but the repository list shows where it is, such as Repositories › crm-api › bulk-import › Task #12, each part linking to its page.
3. **Quick switcher.** Ctrl+K (⌘K on macOS), or a **Jump to…** button in the header, opens a switcher that finds repositories, requirements and tasks by name, id or branch as you type, and opens the one picked with Enter or a click. Before you type, it lists the active tasks. It works by keyboard and screen reader, and Esc closes it, returning focus to where it was.
4. **Section links.** The repository and task pages have links to their sections that stay in view while scrolling and mark the section on screen.
5. **Shortcuts.** `?` lists every shortcut: at least the switcher, `g r` for the repository list and `g u` for one level up. Single-key shortcuts never fire while typing in a field, and a switch in that list turns them off, remembered in that browser.
6. **Look.** Buttons, inputs, tables and statuses share one dense style, built from tokens for colour, spacing, type, radius and focus. Statuses are pills that always carry their text. List pages use the window's width. Keyboard focus is always visible.
7. **Less clutter.** Help that explains a section folds under a **How this works** disclosure instead of standing as paragraphs. An empty state says what to do next and offers the action.
8. **Times** read as relative ("3 min ago"), with the exact time on hover.
9. **Confirmations** such as saved, fetched or removed appear as a brief toast that screen readers announce. Errors stay inline where they happened.
10. Both colour schemes meet WCAG AA contrast, motion follows the reduced-motion setting, and every page reads and works without JavaScript, apart from the switcher and shortcuts.

## Out of scope

- New pages, such as a list of every task, and full-text search.
- Changing what a page shows, beyond its help text and empty states.
- Upgrading htmx, or loading pages through it.
- A CSS framework or web font: the stylesheet stays hand-written, on the system fonts.

## Implementation Notes

- `.claude/rules/web-ui.md` changes with it: one shared script for the switcher, shortcuts and section links loads on every page, a per-browser setting may live in `localStorage`, and "Minimal CSS" becomes the token set. `specs/architecture.md` describes the shell.
- The switcher's results are a server-rendered fragment that htmx fetches as you type. The script only moves the selection and opens it, as a WAI-ARIA combobox in a native `<dialog>`.
- The sidebar reads only the database, so it adds no git call to a page.
- `tests/test_stylesheet.py` covers every new colour token.
