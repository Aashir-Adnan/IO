import { icon } from "../vendor/icons.js";
import { mountFolders } from "../views/library.js";
import { updateMessage } from "../updates.js";
import { syncMessage } from "../sync.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function mountAccount(box, ctx) {
  let timer = null;
  const load = () => ctx.api.sync().then(paint).catch(() => paint(null));
  const paint = (s) => {
    const m = syncMessage(s);
    box.innerHTML = `
      ${m.where ? `<p class="settings-note">${esc(m.where)}</p>` : ""}
      <p class="settings-note upd-msg">${esc(m.text)}</p>
      <div class="upd-actions">
        ${m.canSignIn ? '<button type="button" class="upd-btn primary" data-act="in">Sign in with Google</button>' : ""}
        ${m.canSync ? `<button type="button" class="upd-btn" data-act="now" ${m.busy ? "disabled" : ""}>Sync now</button>` : ""}
        ${m.canSignOut ? '<button type="button" class="upd-btn" data-act="out">Sign out</button>' : ""}
      </div>`;
    const on = (act, fn) => {
      const b = box.querySelector(`[data-act="${act}"]`);
      if (b) b.onclick = async () => {
        b.disabled = true;
        try { await fn(); } catch { /* the next status shows the error */ }
        load();
      };
    };
    on("in", () => ctx.api.syncSignIn());
    on("out", () => ctx.api.syncSignOut());
    on("now", async () => { paint({ ...s, syncing: true }); await ctx.api.syncNow(); });
    ctx.setSync(s);
    clearTimeout(timer);
    if (m.busy && box.isConnected) timer = setTimeout(load, 1500);   // follow a sign-in / sync
  };
  load();
}

function mountUpdates(box, ctx) {
  const paint = (u, note = "") => {
    const m = updateMessage(u);
    const where = u && u.branch ? `${esc(u.branch)} @ ${esc(u.sha)} · ` : "";
    const when = u && u.checked_at ? new Date(u.checked_at * 1000).toLocaleString() : "not yet";
    const subjects = ((u && u.subjects) || []).map((s) => `<li>${esc(s)}</li>`).join("");
    box.innerHTML = `
      <p class="settings-note">${where}last checked ${esc(when)}</p>
      <p class="settings-note upd-msg">${esc(m.text)}</p>
      ${subjects ? `<ul class="upd-list">${subjects}</ul>` : ""}
      ${m.blocked ? `<p class="settings-note">${esc(m.blocked)}</p>` : ""}
      ${note ? `<p class="settings-note">${esc(note)}</p>` : ""}
      <div class="upd-actions">
        <button type="button" class="upd-btn" data-act="check">Check now</button>
        ${m.canApply ? '<button type="button" class="upd-btn primary" data-act="apply">Update &amp; restart</button>' : ""}
      </div>`;
    box.querySelector('[data-act="check"]').onclick = async (e) => {
      e.currentTarget.disabled = true;
      try { const n = await ctx.api.update(true); ctx.setUpdate(n); paint(n); }
      catch (err) { paint(u, String(err.message || err)); }
    };
    const ap = box.querySelector('[data-act="apply"]');
    if (ap) {
      let armed = false;                     // two taps, like the memory browser's delete
      ap.onclick = async () => {
        if (!armed) {
          armed = true;
          ap.textContent = "Confirm: close IO and update";
          setTimeout(() => { armed = false; ap.textContent = "Update & restart"; }, 5000);
          return;
        }
        ap.disabled = true;
        try {
          await ctx.api.applyUpdate();
          box.insertAdjacentHTML("beforeend",
            '<p class="settings-note">Updating… IO will close and reopen shortly.</p>');
        } catch (err) { paint(u, err.detail || String(err.message || err)); }
      };
    }
  };
  ctx.api.update().then((u) => { ctx.setUpdate(u); paint(u); }).catch(() => paint(null));
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
          <div class="settings-sec-h">Account &amp; sync</div>
          <div class="settings-account"></div>
        </section>
        <section class="settings-sec">
          <div class="settings-sec-h">Updates</div>
          <div class="settings-updates"></div>
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
    mountAccount(el.querySelector(".settings-account"), ctx);
    mountUpdates(el.querySelector(".settings-updates"), ctx);
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
