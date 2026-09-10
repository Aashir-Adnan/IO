import { icon } from "../vendor/icons.js";
import { WavRecorder } from "../vendor/recorder.js";
import { Lightbox } from "../components/lightbox.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
const base = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || p;
const fmtSize = (b) => {
  if (b == null) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(0)} KB`;
  if (b < 1073741824) return `${(b / 1048576).toFixed(1)} MB`;
  return `${(b / 1073741824).toFixed(1)} GB`;
};

const KIND_FILTERS = [
  { key: "all", label: "All files", glyph: "images" },
  { key: "image", label: "Photos", glyph: "image" },
  { key: "video", label: "Videos", glyph: "filmSlate" },
  { key: "audio", label: "Voice notes", glyph: "waveform" },
  { key: "doc", label: "Documents", glyph: "fileText" },
];
const kindOf = (it) =>
  it.media_kind === "image" || it.media_kind === "photo" ? "image"
    : it.media_kind === "video" ? "video"
    : it.media_kind === "audio" ? "audio" : "doc";

// ── the full library view (mockup 3c) ────────────────────────────────────
export function mount(root, ctx) {
  root.innerHTML = `
    <section class="library">
      <nav class="lib-nav"></nav>
      <div class="lib-main">
        <div class="lib-crumb"></div>
        <div class="lib-body">
          <div class="lib-col">
            <div class="lib-grid"></div>
            <form class="lib-ask">
              <input type="text" placeholder="Ask about anything in this folder" aria-label="Ask" />
              <button type="button" class="lib-ask-mic" aria-label="Voice">${icon("mic", { size: 17 })}</button>
              <button type="submit" aria-label="Send">${icon("arrowUp", { size: 16 })}</button>
            </form>
          </div>
          <aside class="lib-insp"></aside>
        </div>
      </div>
    </section>`;

  const nav = root.querySelector(".lib-nav");
  const crumb = root.querySelector(".lib-crumb");
  const grid = root.querySelector(".lib-grid");
  const insp = root.querySelector(".lib-insp");
  const status = document.getElementById("status");

  let open = ctx.store.get().gallery || null;   // gallery card: {folder_path, count, items}
  let filter = "all";
  let selected = null;
  let roots = [];
  let fstat = {};
  let lview = localStorage.getItem("io.lib.view") || "grid";   // grid | list
  let lsize = localStorage.getItem("io.lib.size") || "md";     // sm | md | lg
  let indexTimer = null;

  async function loadRoots() {
    try { roots = (await ctx.api.files()).roots || []; } catch { roots = []; }
    try { fstat = await ctx.api.filesStatus(); } catch { fstat = {}; }
    if (status) {
      status.innerHTML = `<span class="live">ON DEVICE</span><span>INDEXED ${
        (fstat.indexed ?? 0).toLocaleString()
      } FILE${fstat.indexed === 1 ? "" : "S"}${fstat.stale ? ` · ${fstat.stale} STALE` : ""}</span>`;
    }
    renderNav();
  }

  async function openFolder(path) {
    try {
      const card = await ctx.api.openFolder({ path });
      open = { type: "gallery", ...card };
      ctx.store.set({ gallery: open });
      selected = null;
      filter = "all";
      renderAll();
      watchIndexing(path);
    } catch { /* ignore */ }
  }

  // media is listed instantly and indexed in the background; poll until the
  // queue drains, then refresh once so captions / entity links appear.
  async function watchIndexing(path) {
    clearTimeout(indexTimer);
    let s = {};
    try { s = await ctx.api.filesStatus(); } catch { /* offline */ }
    fstat = { ...fstat, ...s };
    renderCrumb();
    if (!(s.queue_depth || s.pending)) return;
    indexTimer = setTimeout(async () => {
      if (!open || open.folder_path !== path) return;
      try {
        const card = await ctx.api.openFolder({ path });
        const cur = selected && selected.path;
        open = { type: "gallery", ...card };
        ctx.store.set({ gallery: open });
        selected = cur ? (open.items.find((it) => it.path === cur) || null) : null;
        renderAll();
      } catch { /* ignore */ }
      watchIndexing(path);
    }, 2600);
  }

  function renderNav() {
    const openPath = open && open.folder_path;
    const foldersHtml = roots.length
      ? roots.map((r) => `
          <div class="lib-nav-item${openPath === r.path ? " on" : ""}">
            <button class="lib-nav-open" data-path="${esc(r.path)}" title="${esc(r.path)}">
              ${icon(r.kind === "dir" ? "folder" : "fileText", { size: 14 })}
              <span>${esc(base(r.path))}</span>
            </button>
            <button class="lib-nav-forget" data-path="${esc(r.path)}" title="Stop tracking this folder">${icon("x", { size: 12 })}</button>
          </div>`).join("")
      : `<div class="lib-msg">No folders indexed yet.</div>`;

    const filterHtml = open ? `
      <div class="lib-nav-group">SHOW</div>
      ${KIND_FILTERS.map((f) => `
        <button class="lib-nav-item dim${filter === f.key ? " on" : ""}" data-filter="${f.key}">
          ${icon(f.glyph, { size: 14 })}<span>${f.label}</span>
        </button>`).join("")}` : "";

    nav.innerHTML = `
      <div class="lib-nav-top">
        <button class="lib-nav-back" title="Back to chat">${icon("chatDots", { size: 18 })}</button>
      </div>
      <div class="lib-nav-group">FOLDERS</div>
      ${foldersHtml}
      <button class="lib-nav-pick">${icon("folderOpen", { size: 14 })} Choose folder…</button>
      ${filterHtml}`;

    nav.querySelectorAll(".lib-nav-open[data-path]").forEach((b) => {
      b.onclick = () => openFolder(b.dataset.path);
    });
    nav.querySelectorAll(".lib-nav-forget[data-path]").forEach((b) => {
      b.onclick = async (e) => {
        e.stopPropagation();
        if (!b.classList.contains("confirm")) {
          b.classList.add("confirm"); b.textContent = "forget?";
          setTimeout(() => { b.classList.remove("confirm"); b.innerHTML = icon("x", { size: 12 }); }, 2500);
          return;
        }
        try { await ctx.api.forgetFile(b.dataset.path); } catch { /* ignore */ }
        if (open && open.folder_path === b.dataset.path) { open = null; selected = null; ctx.store.set({ gallery: null }); }
        await loadRoots();
        renderAll();
      };
    });
    nav.querySelectorAll(".lib-nav-item[data-filter]").forEach((b) => {
      b.onclick = () => { filter = b.dataset.filter; renderAll(); };
    });
    nav.querySelector(".lib-nav-pick").onclick = pickFolder;
    nav.querySelector(".lib-nav-back").onclick = () => ctx.goto("conversation");
  }

  async function pickFolder() {
    const picker = window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder;
    if (!picker) {
      grid.innerHTML = `<div class="lib-empty">Folder picker needs the desktop app.</div>`;
      return;
    }
    try {
      const chosen = await window.pywebview.api.pick_folder();
      if (!chosen) return;
      await ctx.api.registerFile(chosen);
      await loadRoots();
      openFolder(chosen);
    } catch (e) {
      grid.innerHTML = `<div class="lib-empty">Couldn't add that folder — ${
        e.status === 404
          ? "file indexing is off in config.toml ([files] enabled)"
          : (e.detail || "not allowed or not found")
      }.</div>`;
    }
  }

  function renderCrumb() {
    if (!open) { crumb.innerHTML = ""; return; }
    const busy = (fstat.queue_depth || 0) + (fstat.pending || 0);
    crumb.innerHTML = `
      <span>FILES</span>
      ${icon("caretRight", { size: 10, cls: "cr-sep" })}
      <span class="cr-cur">${esc(base(open.folder_path)).toUpperCase()}</span>
      ${busy ? `<span class="cr-indexing">${icon("circleNotch", { size: 12 })} indexing ${busy}…</span>` : ""}
      <span class="cr-tools">
        <button class="cr-tool${lview === "grid" ? " on" : ""}" data-view="grid" title="Grid">${icon("squaresFour", { size: 14 })}</button>
        <button class="cr-tool${lview === "list" ? " on" : ""}" data-view="list" title="List">${icon("list", { size: 14 })}</button>
        <span class="cr-tools-sep"></span>
        <button class="cr-tool" data-size="down" title="Smaller"${lsize === "sm" ? " disabled" : ""}>${icon("minus", { size: 13 })}</button>
        <button class="cr-tool" data-size="up" title="Larger"${lsize === "lg" ? " disabled" : ""}>${icon("plus", { size: 13 })}</button>
      </span>`;
    crumb.querySelectorAll(".cr-tool[data-view]").forEach((b) => {
      b.onclick = () => { lview = b.dataset.view; localStorage.setItem("io.lib.view", lview); renderCrumb(); renderGrid(); };
    });
    crumb.querySelectorAll(".cr-tool[data-size]").forEach((b) => {
      b.onclick = () => {
        const order = ["sm", "md", "lg"];
        const i = order.indexOf(lsize) + (b.dataset.size === "up" ? 1 : -1);
        if (i < 0 || i > 2) return;
        lsize = order[i]; localStorage.setItem("io.lib.size", lsize);
        renderCrumb(); renderGrid();
      };
    });
  }

  function items() {
    const all = (open && open.items) || [];
    return filter === "all" ? all : all.filter((it) => kindOf(it) === filter);
  }

  // double-click / "open" — media → lightbox, text file → text viewer
  async function openItem(it) {
    const k = kindOf(it);
    if ((k === "image" || k === "video") && it.raw_url) {
      Lightbox({ raw_url: it.raw_url, kind: k });
      return;
    }
    if (k === "doc") {
      try {
        const doc = await ctx.api.fileContent(it.path);
        Lightbox({ text: doc.text, name: doc.title || base(it.path) });
      } catch { /* not text / too big */ }
    }
  }

  function renderGrid() {
    if (!open) {
      grid.innerHTML = `<div class="lib-empty">Pick a folder on the left to browse it here.</div>`;
      return;
    }
    grid.dataset.view = lview;
    grid.dataset.size = lsize;
    const all = items();
    if (!all.length) { grid.innerHTML = `<div class="lib-empty">Nothing here yet.</div>`; return; }
    const MAX = lview === "list" ? 800 : 400;
    const its = all.slice(0, MAX);
    grid.innerHTML = "";
    for (const it of its) {
      const tile = document.createElement("button");
      tile.className = "lib-tile" + (selected && selected.path === it.path ? " on" : "");
      const k = kindOf(it);
      const glyph = k === "audio" ? "waveform"
        : k === "video" ? "filmSlate"
        : it.media_kind === "doc" ? "fileText" : "file";
      tile.innerHTML = `
        <span class="lib-tile-thumb">${
          it.thumb_url
            ? `<img loading="lazy" src="${it.thumb_url}" alt="">`
            : icon(k === "image" ? "image" : glyph, { size: 34 })
        }${k === "video" ? `<span class="tile-play">${icon("play", { size: 20 })}</span>` : ""}</span>
        <span class="lib-tile-name">${esc(base(it.path))}${
          it.size_bytes != null ? `<span> · ${fmtSize(it.size_bytes)}</span>` : ""
        }</span>`;
      tile.onclick = () => { selected = it; renderGrid(); renderInspector(); };
      tile.ondblclick = () => openItem(it);
      grid.appendChild(tile);
    }
    if (all.length > MAX) {
      const more = document.createElement("div");
      more.className = "lib-more";
      more.textContent = `+${all.length - MAX} more\nfilter to narrow`;
      grid.appendChild(more);
    }
  }

  function renderInspector() {
    const it = selected;
    if (!it) {
      insp.innerHTML = `<div class="lib-insp-empty">Select a file to see IO's caption and the records it's linked to.</div>`;
      return;
    }
    const k = kindOf(it);
    insp.innerHTML = `
      <div class="lib-insp-preview">${
        k === "video" && it.raw_url
          ? `<video controls preload="metadata" src="${it.raw_url}"></video>`
          : k === "image" && it.raw_url
            ? `<img src="${it.raw_url}" alt="">`
            : icon(k === "audio" ? "waveform" : it.media_kind === "doc" ? "fileText" : "file", { size: 44 })
      }</div>
      <div>
        <div class="lib-insp-name">${esc(base(it.path))}</div>
        <div class="lib-insp-meta">${esc(it.path)}</div>
      </div>
      <div class="lib-insp-hair"></div>
      <div>
        <h4>IO's caption</h4>
        <div class="lib-insp-cap" contenteditable="plaintext-only" spellcheck="false"
             data-placeholder="No caption yet — type one and press Enter">${esc(it.caption || "")}</div>
        <div class="lib-insp-gate" hidden></div>
      </div>
      <div>
        <h4>Linked records</h4>
        <div class="chips lib-insp-chips">${
          (it.entities || []).map((e) =>
            `<button class="chip${e.etype === "person" ? " person" : ""}" data-etype="${e.etype}" data-id="${e.id}">${esc(e.name)}</button>`).join("")
          || `<span class="lib-msg">none yet</span>`
        }</div>
      </div>
      <span class="grow"></span>
      <button class="btn btn-primary lib-insp-ask">Ask about this ${k === "audio" ? "note" : k === "video" ? "video" : "photo"}</button>`;

    const pv = insp.querySelector(".lib-insp-preview");
    if (k === "image" || k === "video" || k === "doc") {
      pv.style.cursor = "zoom-in";
      pv.onclick = () => openItem(it);
    }

    const cap = insp.querySelector(".lib-insp-cap");
    cap.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); cap.blur(); }
    });
    cap.addEventListener("blur", async () => {
      const text = cap.textContent.trim();
      if (!text || text === (it.caption || "").trim()) return;
      try {
        const res = await ctx.api.caption(it.path, text, "text");
        if (res.gated) return showGate(it, res.pending_token, res.reasons);
        applyCaption(it, res);
      } catch { /* ignore */ }
    });

    insp.querySelectorAll(".lib-insp-chips .chip[data-etype]").forEach((c) => {
      c.onclick = () => ctx.openInspector && ctx.openInspector(c.dataset.etype, +c.dataset.id);
    });
    insp.querySelector(".lib-insp-ask").onclick = () => {
      ctx._pending = `Tell me about ${base(it.path)}`;
      ctx.goto("conversation");
    };
  }

  function applyCaption(it, res) {
    it.caption = res.caption;
    it.entities = res.entities || it.entities;
    renderInspector();
    renderGrid();
  }

  function showGate(it, token, reasons) {
    const gate = insp.querySelector(".lib-insp-gate");
    gate.hidden = false;
    gate.innerHTML =
      `<p>${esc((reasons || []).join(" ")) || "Save this caption and its links?"}</p>` +
      `<button class="btn btn-primary" data-yes>Save</button><button class="btn" data-no>Discard</button>`;
    gate.querySelector("[data-yes]").onclick = async () => {
      gate.hidden = true;
      try { applyCaption(it, await ctx.api.captionConfirm(token)); } catch { /* ignore */ }
    };
    gate.querySelector("[data-no]").onclick = () => { gate.hidden = true; renderInspector(); };
  }

  function renderAll() { renderNav(); renderCrumb(); renderGrid(); renderInspector(); }

  // folder-level ask bar
  const askForm = root.querySelector(".lib-ask");
  const askInput = askForm.querySelector("input");
  askForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = askInput.value.trim();
    if (!v) return;
    askInput.value = "";
    ctx._pending = v;
    ctx.goto("conversation");
  });
  let rec = null;
  const askMic = askForm.querySelector(".lib-ask-mic");
  askMic.addEventListener("click", async () => {
    if (rec) {
      askMic.classList.remove("rec");
      const blob = await rec.stop(); rec = null;
      try {
        const { transcript } = await ctx.api.transcribeAudio(blob);
        if (transcript) { askInput.value = transcript; askInput.focus(); }
      } catch { /* ignore */ }
      return;
    }
    if (!ctx.store.get().voiceOk) { ctx.openSettings(); return; }
    try { rec = new WavRecorder(); await rec.start(); askMic.classList.add("rec"); }
    catch { rec = null; }
  });

  renderAll();
  loadRoots();

  root._cleanup = () => {
    clearTimeout(indexTimer);
    if (rec) { try { rec.stop(); } catch { /* ignore */ } }
  };
}

// ── compact folder manager, mounted inside the settings sheet ────────────
export function mountFolders(host, ctx) {
  let timer = null;

  host.innerHTML = `
    <div class="lib-folders">
      <button type="button" class="lib-nav-pick">${icon("folderOpen", { size: 14 })} Choose folder…</button>
      <form class="lib-folders-add">
        <input type="text" name="path" placeholder="…or paste a file / folder path" />
        <button type="submit" class="btn">Add</button>
      </form>
      <div class="lib-folders-msg" hidden></div>
      <div class="lib-folders-list"></div>
    </div>`;

  const listEl = host.querySelector(".lib-folders-list");
  const msg = host.querySelector(".lib-folders-msg");
  const pathInput = host.querySelector('input[name="path"]');

  async function addPath(path) {
    if (!path) return;
    try {
      const r = await ctx.api.registerFile(path);
      msg.hidden = false; msg.textContent = `Added — ${r.discovered} file(s), indexing…`;
      poll();
    } catch (e) {
      msg.hidden = false;
      msg.textContent = e.status === 404
        ? "File indexing is turned off in config.toml ([files] enabled)."
        : `Couldn't add that path — ${e.detail || "not allowed or not found"}.`;
    }
  }

  host.querySelector(".lib-nav-pick").onclick = async () => {
    const picker = window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder;
    if (!picker) { pathInput.focus(); return; }
    try {
      const chosen = await window.pywebview.api.pick_folder();
      if (chosen) addPath(chosen);
    } catch { pathInput.focus(); }
  };
  host.querySelector(".lib-folders-add").addEventListener("submit", (e) => {
    e.preventDefault();
    const p = pathInput.value.trim();
    if (!p) return;
    pathInput.value = "";
    addPath(p);
  });

  async function render() {
    let roots = [];
    try { roots = (await ctx.api.files()).roots || []; } catch { /* offline */ }
    let s = {};
    try { s = await ctx.api.filesStatus(); } catch { /* ignore */ }
    listEl.innerHTML = roots.length
      ? roots.map((r) => `
          <div class="lib-folder-row">
            <span class="lf-name">${icon(r.kind === "dir" ? "folder" : "fileText", { size: 15 })} ${esc(r.path)}</span>
            <span class="lf-stats">${s.indexed ?? 0}/${s.total ?? 0}${s.stale ? ` · ${s.stale} stale` : ""}</span>
            <button class="lf-reindex" data-path="${esc(r.path)}">Reindex</button>
            <button class="lf-remove" data-path="${esc(r.path)}">Remove</button>
          </div>`).join("")
      : `<div class="lib-msg">No folders registered yet.</div>`;
    listEl.querySelectorAll(".lf-reindex").forEach((b) => {
      b.onclick = async () => { await ctx.api.reindexFiles(b.dataset.path); poll(); };
    });
    listEl.querySelectorAll(".lf-remove").forEach((b) => {
      b.onclick = async () => { await ctx.api.forgetFile(b.dataset.path); render(); };
    });
  }

  async function poll() {
    let s = {};
    try { s = await ctx.api.filesStatus(); } catch { /* ignore */ }
    await render();
    clearTimeout(timer);
    if (s.queue_depth) timer = setTimeout(poll, 2500);
  }

  render();
}
