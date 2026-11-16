"use strict";

// Apply before styles paint. Only these display preferences enter local storage.
(() => {
  const key = "trace.display";
  const palettes = ["flight", "graphite", "ubuntu"];
  const modes = ["light", "dark", "system"];
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const root = document.documentElement;
  let preference;

  function validate(value) {
    return {
      palette: palettes.includes(value?.palette) ? value.palette : "flight",
      mode: modes.includes(value?.mode) ? value.mode : "light"
    };
  }

  function read(value) {
    try {
      return validate(JSON.parse(value));
    } catch {
      return validate(null);
    }
  }

  function apply() {
    root.dataset.tracePalette = preference.palette;
    root.dataset.bsTheme = preference.mode === "system"
      ? (systemDark.matches ? "dark" : "light") : preference.mode;
    document.querySelectorAll("[data-theme-palette]").forEach(select => {
      select.value = preference.palette;
    });
    document.querySelectorAll("[data-theme-mode]").forEach(select => {
      select.value = preference.mode;
    });
  }

  try {
    preference = read(window.localStorage.getItem(key));
  } catch {
    preference = validate(null);
  }
  apply();
  systemDark.addEventListener("change", () => {
    if (preference.mode === "system") apply();
  });
  window.addEventListener("storage", event => {
    if (event.key === key || event.key === null) {
      preference = read(event.newValue);
      apply();
    }
  });
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-theme-picker]").forEach(picker => {
      picker.hidden = false;
      picker.addEventListener("change", event => {
        if (event.target.matches("[data-theme-palette]")) {
          preference = validate({...preference, palette: event.target.value});
        } else if (event.target.matches("[data-theme-mode]")) {
          preference = validate({...preference, mode: event.target.value});
        } else {
          return;
        }
        apply();
        try {
          window.localStorage.setItem(key, JSON.stringify(preference));
        } catch {
          // Browsers that block storage can still switch this page's appearance.
        }
      });
    });
    apply();
  });
})();
