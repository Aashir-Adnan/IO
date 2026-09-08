import { icon } from "../vendor/icons.js";
import { mount as mountFolders } from "../views/files.js";

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
