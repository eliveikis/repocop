// The shell's behaviour on every page: the quick switcher (Ctrl+K, or ⌘K on macOS), the single-key
// shortcuts, marking the section on screen in a page's section links, and having screen readers
// announce a toast. Every page reads and works without it, but for the switcher and shortcuts.
(() => {
  "use strict";

  const SINGLE_KEYS = "repocop.single-key-shortcuts"; // "off" once turned off in this browser
  const SEQUENCE_MS = 1500; // how long `g` waits for the key after it
  const mac = /Mac|iPhone|iPad/.test(navigator.userAgentData?.platform || navigator.platform || "");

  // ------------------------------------------------------------- dialogs

  function openDialog(dialog) {
    if (dialog.open) return;
    let returnTo = document.activeElement;
    for (const other of document.querySelectorAll("dialog[open]")) {
      returnTo = other.returnTo || returnTo; // focus goes back to where it was before either
      other.returnTo = null;
      other.close();
    }
    dialog.returnTo = returnTo;
    dialog.showModal();
  }

  for (const dialog of document.querySelectorAll("dialog")) {
    dialog.addEventListener("close", () => {
      if (dialog.returnTo && dialog.returnTo.isConnected) dialog.returnTo.focus();
      dialog.returnTo = null;
      // nothing was focused before: leave nothing focused, rather than the closed dialog's field
      if (dialog.contains(document.activeElement)) document.activeElement.blur();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close(); // a click on the backdrop
    });
  }
  for (const button of document.querySelectorAll("[data-closes]")) {
    button.addEventListener("click", () => button.closest("dialog").close());
  }

  // ------------------------------------------------------------- quick switcher

  const jump = document.getElementById("jump");
  const input = document.getElementById("jump-input");
  const count = document.getElementById("jump-count");

  const options = () => Array.from(jump.querySelectorAll('[role="option"]'));

  function select(option) {
    for (const each of options()) each.setAttribute("aria-selected", String(each === option));
    if (option) {
      input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function refresh() {
    const found = options();
    input.setAttribute("aria-expanded", String(found.length > 0));
    select(found[0] || null);
    count.textContent = found.length
      ? `${found.length} ${found.length === 1 ? "result" : "results"}`
      : "No results";
  }

  function openJump() {
    openDialog(jump);
    input.value = "";
    input.focus();
    if (window.htmx) window.htmx.trigger(input, "jumpopen");
  }

  input.addEventListener("keydown", (event) => {
    const found = options();
    const current = found.findIndex((o) => o.getAttribute("aria-selected") === "true");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!found.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = current < 0 ? (step > 0 ? 0 : found.length - 1) : current + step;
      select(found[(next + found.length) % found.length]);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (current >= 0) found[current].click();
    }
  });
  jump.addEventListener("pointermove", (event) => {
    const option = event.target.closest('[role="option"]');
    if (option && option.getAttribute("aria-selected") !== "true") select(option);
  });
  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (jump.contains(event.target)) refresh();
  });

  // ------------------------------------------------------------- shortcuts

  const shortcuts = document.getElementById("shortcuts");
  const toggle = document.getElementById("single-keys");
  let singleKeys = true;
  try {
    singleKeys = localStorage.getItem(SINGLE_KEYS) !== "off";
  } catch {
    // storage is blocked: the shortcuts stay on, and a change lasts until the page is left
  }
  toggle.checked = singleKeys;
  toggle.addEventListener("change", () => {
    singleKeys = toggle.checked;
    try {
      if (singleKeys) localStorage.removeItem(SINGLE_KEYS);
      else localStorage.setItem(SINGLE_KEYS, "off");
    } catch {
      // not remembered, as above
    }
  });

  const opens = { jump: openJump, shortcuts: () => openDialog(shortcuts) };
  for (const button of document.querySelectorAll("[data-opens]")) {
    button.hidden = false;
    button.addEventListener("click", () => opens[button.dataset.opens]());
  }
  for (const key of document.querySelectorAll(".mod-key")) key.textContent = mac ? "⌘" : "Ctrl";

  // A field of a dialog that has just closed can keep focus until its close event, so it doesn't count.
  const typing = (target) =>
    target instanceof Element &&
    target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])') !== null &&
    target.closest("dialog:not([open])") === null;

  function goUp() {
    const crumbs = document.querySelectorAll(".breadcrumbs a");
    if (crumbs.length > 1) window.location.href = crumbs[crumbs.length - 2].href;
  }

  let gPressedAt = 0;
  document.addEventListener("keydown", (event) => {
    const modifier = mac ? event.metaKey : event.ctrlKey;
    if (modifier && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (jump.open) jump.close();
      else openJump();
      return;
    }
    if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    if (!singleKeys || typing(event.target) || document.querySelector("dialog[open]")) return;
    const afterG = gPressedAt > 0 && Date.now() - gPressedAt < SEQUENCE_MS;
    gPressedAt = 0;
    if (event.key === "?") {
      event.preventDefault();
      openDialog(shortcuts);
    } else if (event.key === "g" && !afterG) {
      gPressedAt = Date.now();
    } else if (afterG && event.key === "r") {
      event.preventDefault();
      window.location.href = document.querySelector(".brand").href;
    } else if (afterG && event.key === "u") {
      event.preventDefault();
      goUp();
    }
  });

  // ------------------------------------------------------------- section links

  const sectionLinks = document.querySelector(".section-links");
  if (sectionLinks) {
    const links = Array.from(sectionLinks.querySelectorAll('a[href^="#"]'));
    const sections = links.map((link) => document.getElementById(decodeURIComponent(link.hash.slice(1))));
    let scheduled = false;
    const mark = () => {
      scheduled = false;
      // a section is on screen once its top reaches where a link to it leaves it: its scroll margin
      const margin = parseFloat(getComputedStyle(sections[0] || sectionLinks).scrollMarginTop) || 0;
      const line = Math.max(sectionLinks.getBoundingClientRect().bottom, margin) + 8;
      let current = 0;
      sections.forEach((section, index) => {
        if (section && section.getBoundingClientRect().top <= line) current = index;
      });
      const page = document.documentElement;
      if (page.scrollHeight > window.innerHeight + 2 && window.innerHeight + window.scrollY >= page.scrollHeight - 2) {
        current = sections.length - 1; // scrolled to the end: the last section is the one in view
      }
      links.forEach((link, index) => {
        if (index === current) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    };
    const schedule = () => {
      if (!scheduled) {
        scheduled = true;
        requestAnimationFrame(mark);
      }
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    document.body.addEventListener("htmx:afterSettle", schedule);
    mark();
  }

  // ------------------------------------------------------------- toasts

  // A live region announces what is added to it, not what a page arrived with: add the toasts
  // again once the page is read, so screen readers announce them.
  const region = document.querySelector(".toasts");
  if (region && region.children.length) {
    const toasts = Array.from(region.children);
    region.replaceChildren();
    setTimeout(() => region.append(...toasts), 250);
  }
})();
