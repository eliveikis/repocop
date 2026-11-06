// A requirement's page: keeps its section asking the requirement's sessions current.
(() => {
  "use strict";

  // The section isn't carried by the session lists' refresh, as what it offers takes a git call.
  // The refreshed list holds a digest of what the section shows: when it differs from the
  // section's, the section is fetched again. Only the entries whose own digest changed are
  // swapped, so a workflow being picked in another stays picked; when the sessions themselves
  // changed, the section is swapped whole, keeping each entry that shows the same.
  let fetching = false;

  function showCopyButtons(root) {
    for (const button of root.querySelectorAll("[data-copy]")) button.hidden = false;
  }

  async function refresh() {
    const section = document.getElementById("ask");
    const list = document.querySelector(".sessions[data-asking-shows]");
    if (!section || !list || fetching) return;
    if (list.dataset.askingShows === section.dataset.askingShows) return;
    fetching = true;
    try {
      const response = await fetch(section.dataset.src);
      if (!response.ok) return;
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const fresh = page.getElementById("ask");
      if (!fresh) return;
      showCopyButtons(fresh);
      const shown = Array.from(section.querySelectorAll(".ask[id]"));
      const now = Array.from(fresh.querySelectorAll(".ask[id]"));
      const same = shown.length === now.length && shown.every((e, i) => e.id === now[i].id);
      if (same) {
        now.forEach((entry, i) => {
          if (entry.dataset.shows !== shown[i].dataset.shows) shown[i].replaceWith(entry);
        });
        section.dataset.askingShows = fresh.dataset.askingShows;
        section.hidden = fresh.hidden;
      } else {
        for (const entry of now) {
          const kept = document.getElementById(entry.id);
          if (kept && kept.dataset.shows === entry.dataset.shows) entry.replaceWith(kept);
        }
        section.replaceWith(fresh);
      }
    } catch {
      // not reached: the next refresh tries again
    } finally {
      fetching = false;
    }
  }

  document.body.addEventListener("htmx:oobAfterSwap", refresh);
})();
