# UI

RepoCop's pages are for an operator watching many repositories and sessions at once: every page shares one frame, so they see which session needs them and get to any repository, requirement or template sync quickly. Pages are server-rendered, and every page reads and works without JavaScript, but for the switcher, shortcuts and Copy buttons. How pages are built, styled and kept accessible is `.claude/rules/web-ui.md`'s.

## The shell

- **Sidebar:** the repositories, with a link to add one, and the sessions that need input in any of them, each linked to its requirement's page, or else its repository's. In a narrow window it is behind a Menu button, which needs no script.
- **Breadcrumbs** on every page but the repository list, such as Repositories › crm-api › bulk-import, each part a link.
- **Quick switcher:** Ctrl+K (⌘K on macOS), or Jump to…, opens a search, from the keyboard and to screen readers alike, of the repositories and requirements whose name holds what was typed, and the template syncs by number or branch. Requirements are those in each checkout's requirements folder, read as a requirement's page reads them.
- **Shortcuts:** `?` lists them, `g r` goes to the repository list and `g u` one level up, by the breadcrumbs. Single-key shortcuts never fire in a field, and a switch in the list turns them off, remembered in that browser.
- **Section links** on the repository and template sync pages stay in view and mark the section on screen.
- **Copy buttons** put a line, such as the one that runs a workflow, on the clipboard. Where the clipboard can't be written, as on a page served neither from the machine itself nor over HTTPS, the button selects the line instead, and without the script the line is copied by hand.
- **Toasts** carry confirmations, such as fetched, removed or copied, in a live region that screen readers announce; errors stay inline. Times read as relative, with the exact time on hover. Help that explains a section folds under **How this works**.
- **Both colour schemes** meet WCAG AA contrast, and motion follows the reduced-motion setting.

## Staying current

- **What the shell shows costs each page little**, whatever the number of repositories and sessions, since it is on every page and refreshes every 2 s: it reads the database and the session logs as files, and once each repository's log folder is known, starts no process. Starting one per repository on each page or refresh is what breaks it.
- **Session lists refresh on their own.** Every session list a page shows, the sidebar's included, refreshes every 2 s while the page is visible, its tab the one showing and its window not minimised, and once as soon as it is visible again, so a page in the background asks for nothing. A refresh changes nothing, makes no git call and doesn't read GitHub, so the rest of a page, such as a board's stages, is as of its load.
- **A template sync's page** doesn't refresh itself, as a sync is done within the request that applies it ([template-sync.md › A sync's page](template-sync.md#a-syncs-page)).

## Editor links

When `editor_url` is configured, each primary checkout, sync worktree and requirement file that is on disk gets an "Open in editor" link built from it. The link is opened by the browser's machine. RepoCop launches nothing, so it also works when the browser isn't on RepoCop's host.
