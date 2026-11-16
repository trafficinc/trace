"use strict";

const navigationButtons = document.querySelectorAll("[data-sidebar-toggle]");
let navigationOpener;
function setNavigation(open, restoreFocus = false) {
  document.body.classList.toggle("trace-navigation-open", open);
  navigationButtons.forEach(button => button.setAttribute("aria-expanded", String(open)));
  if (open) document.querySelector(".trace-sidebar-close")?.focus();
  else if (restoreFocus) navigationOpener?.focus();
}
navigationButtons.forEach(button => button.addEventListener("click", () => {
  const open = !document.body.classList.contains("trace-navigation-open");
  if (open) navigationOpener = button;
  setNavigation(open, !open);
}));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("trace-navigation-open")) setNavigation(false, true);
});
document.addEventListener("click", event => {
  if (!event.target.closest("#sidebar") && !event.target.closest("[data-sidebar-toggle]")) setNavigation(false);
});
window.matchMedia("(min-width: 761px)").addEventListener("change", event => {
  if (event.matches) setNavigation(false);
});

// Preserve server-rendered validation errors and stale drafts in their intended target.
document.addEventListener("htmx:beforeSwap", event => {
  if ([400, 409, 413, 422, 503, 507].includes(event.detail.xhr.status)) {
    if (event.detail.xhr.status === 409) {
      const source = event.detail.requestConfig?.elt;
      const form = source?.closest("form[data-edit-form]");
      if (form) {
        // Replace only the submitted form; other drafts on the page stay intact.
        event.detail.target = form;
        event.detail.swapOverride = "outerHTML";
      }
    }
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});
const trackedEditors = new WeakSet();
const dirtyEditors = new Set();
function bindEditors() {
  document.querySelectorAll("form").forEach(form => {
    if (form.matches("[data-editor-poll]") || !(form.hasAttribute("data-edit-form") || form.querySelector('input[name="version"], textarea'))) return;
    form.setAttribute("data-edit-form", "");
    if (trackedEditors.has(form)) return;
    trackedEditors.add(form);
    if (form.querySelector(".errorlist") || form.hasAttribute("data-preserved-draft")) dirtyEditors.add(form);
    form.addEventListener("input", () => dirtyEditors.add(form));
    form.addEventListener("change", () => dirtyEditors.add(form));
    form.addEventListener("submit", () => {
      if (!(window.htmx && form.hasAttribute("hx-post"))) dirtyEditors.delete(form);
    });
  });
  for (const form of dirtyEditors) {
    if (!form.isConnected) dirtyEditors.delete(form);
  }
}
bindEditors();
document.addEventListener("htmx:afterSwap", bindEditors);
window.addEventListener("beforeunload", event => {
  if ([...dirtyEditors].some(form => form.isConnected)) {
    event.preventDefault();
    event.returnValue = "";
  }
});

// Authentication/permission changes stop informational polls without losing drafts.
document.addEventListener("htmx:beforeSwap", event => {
  const source = event.detail.requestConfig?.elt;
  if (source?.closest("form[data-edit-form]") && [401, 403, 404].includes(event.detail.xhr.status)) {
    const form = source.closest("form[data-edit-form]");
    dirtyEditors.add(form);
    let notice = form.querySelector("[data-access-error]");
    if (!notice) {
      notice = document.createElement("p");
      notice.setAttribute("data-access-error", "");
      notice.setAttribute("role", "alert");
      form.prepend(notice);
    }
    notice.textContent = "This save is unavailable with your current access. Your draft remains here; check access in another tab.";
    event.detail.shouldSwap = false;
  }
  if (source?.matches("[data-editor-poll]") && [401, 403, 404].includes(event.detail.xhr.status)) {
    source.removeAttribute("hx-trigger");
    source.textContent = "Editor status is unavailable. Your draft remains here; check access in another tab.";
    event.detail.shouldSwap = false;
  }
});
document.addEventListener("htmx:afterRequest", event => {
  const source = event.detail.requestConfig?.elt || event.detail.elt;
  const form = source?.closest("form[data-edit-form]");
  if (form && event.detail.xhr.getResponseHeader("HX-Redirect")) dirtyEditors.delete(form);
});

// An explicit action may refresh a panel containing a different unfinished form.
// Keep that panel in place rather than discarding the other form's inputs.
document.addEventListener("htmx:beforeSwap", event => {
  const source = event.detail.requestConfig?.elt;
  const submitted = source?.closest("form");
  const target = event.detail.target;
  if (event.detail.shouldSwap && target && [...dirtyEditors].some(form =>
      form.isConnected && form !== submitted && target.contains(form))) {
    event.detail.shouldSwap = false;
    let notice = target.previousElementSibling;
    if (!notice?.matches("[data-deferred-refresh]")) {
      notice = document.createElement("p");
      notice.setAttribute("data-deferred-refresh", "");
      notice.setAttribute("role", "status");
      target.insertAdjacentElement("beforebegin", notice);
    }
    notice.textContent = "A section refresh was held to preserve another draft. Finish or copy your drafts before refreshing.";
  }
});

// Poll only informational regions and keep keyboard focus stable during refresh.
document.addEventListener("htmx:beforeRequest", event => {
  if (event.detail.elt?.matches("[data-dashboard-poll]") && document.hidden) event.preventDefault();
});
document.addEventListener("htmx:beforeSwap", event => {
  const source = event.detail.requestConfig?.elt;
  if (!source?.matches("[data-dashboard-poll]")) return;
  if ([401, 403, 404].includes(event.detail.xhr.status)) {
    source.removeAttribute("hx-trigger");
    source.textContent = "This summary is unavailable with your current access. Return to your workspace or sign in again.";
    source.setAttribute("role", "status");
    event.detail.shouldSwap = false;
  } else if (source.contains(document.activeElement)) {
    event.detail.shouldSwap = false;
  }
});

// Django supplies aria-invalid/aria-describedby and visible field error lists.
// Focus the summary after a failed submission without moving focus on polls.
function focusValidation(root) {
  let summary = root.querySelector?.(".trace-form-errors");
  if (!summary) {
    const errors = root.querySelector?.("form .errorlist");
    if (errors) {
      summary = errors;
      summary.classList.add("trace-form-errors");
      summary.setAttribute("tabindex", "-1");
      summary.setAttribute("role", "alert");
    }
  }
  if (summary) summary.focus();
}
focusValidation(document);
document.addEventListener("htmx:afterSwap", event => {
  const method = event.detail.requestConfig?.verb;
  if (method === "post") focusValidation(event.detail.target);
});
