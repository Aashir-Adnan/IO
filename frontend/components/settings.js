import { icon } from "../vendor/icons.js";
import { mountFolders } from "../views/library.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// The single "other place" in the app: window prefs + folder management.
export function Settings(el, scrim, ctx) {
  function render() {
    const s = ctx.store.get();
    el.innerHTML = `
      <header class="settings-head">
        <h2>Settings</h2>
        <button class="settings-close" aria-label="Close">${icon("check", { size: 16 })}</button>
      </header>
      <div class="settings-body">
        <section class="settings-sec">
          <div class="settings-sec-h">Appearance</div>
          <div class="theme-toggle" role="group" aria-label="Theme">
            <button type="button" data-theme-set="dark">Dark</button>
            <button type="button" data-theme-set="light">Light</button>
          </div>
        </section>
        <section class="settings-sec">
          <div class="settings-sec-h">Voice</div>
          <label class="settings-row">
            <span>Speak replies aloud</span>
            <input type="checkbox" id="set-speak" ${s.autoSpeak !== "never" ? "checked" : ""} />
          </label>
          <p class="settings-note">${s.voiceOk ? "Voice ready." : esc(s.voiceReason || "Voice model downloads on first use.")}</p>
        </section>
        <section class="settings-sec">
          <div class="settings-sec-h">Folders IO can read</div>
          <div class="settings-folders"></div>
        </section>
      </div>`;

    el.querySelector(".settings-close").onclick = close;
    el.querySelector("#set-speak").onchange = (e) => {
      ctx.store.set({ autoSpeak: e.target.checked ? "always" : "never" });
    };

    const curTheme = document.documentElement.getAttribute("data-theme") || "dark";
    const tt = el.querySelector(".theme-toggle");
    const paint = () => {
      const t = document.documentElement.getAttribute("data-theme") || "dark";
      tt.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.themeSet === t));
    };
    tt.querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        const t = b.dataset.themeSet;
        document.documentElement.setAttribute("data-theme", t);
        try { localStorage.setItem("io.theme", t); } catch { /* private mode */ }
        paint();
      };
    });
    if (curTheme) paint();

    mountFolders(el.querySelector(".settings-folders"), ctx);
  }

  function open() {
    render();
    el.hidden = false;
    scrim.hidden = false;
    requestAnimationFrame(() => el.classList.add("in"));
  }
  function close() {
    el.classList.remove("in");
    scrim.hidden = true;
    setTimeout(() => { el.hidden = true; }, 180);
  }
  function toggle() { el.hidden ? open() : close(); }

  scrim.addEventListener("click", close);
  return { open, close, toggle };
}
