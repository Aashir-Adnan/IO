import { icon } from "../vendor/icons.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function mount(root, ctx) {
  root.innerHTML = `
    <section class="files-view">
      <header class="files-head">
        <h1>Files</h1>
        <form class="files-add">
          <button type="button" class="files-browse">${icon("folderOpen", { size: 16 })} Choose folder…</button>
          <input type="text" name="path" placeholder="…or paste a file / folder path" />
          <button type="submit">${icon("folders", { size: 16 })} Add</button>
        </form>
        <div class="files-msg" hidden></div>
      </header>
      <div class="files-roots"></div>
    </section>`;

  const rootsEl = root.querySelector(".files-roots");
  const msg = root.querySelector(".files-msg");
  const pathInput = root.querySelector('.files-add input[name="path"]');
  let timer = null;

  async function addPath(path) {
    if (!path) return;
    try {
      const r = await ctx.api.registerFile(path);
      msg.hidden = false;
      msg.textContent = `Added — ${r.discovered} file(s), indexing…`;
      poll();
    } catch {
      msg.hidden = false;
      msg.textContent = "Couldn't add that path (not allowed or not found).";
    }
  }

  root.querySelector(".files-browse").addEventListener("click", async () => {
    const picker = window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder;
    if (!picker) { pathInput.focus(); return; }
    try {
      const chosen = await window.pywebview.api.pick_folder();
      if (chosen) addPath(chosen);
    } catch { pathInput.focus(); }
  });

  async function render() {
    let data = { roots: [] };
    try { data = await ctx.api.files(); } catch { /* offline */ }
    let status = {};
    try { status = await ctx.api.filesStatus(); } catch { /* ignore */ }
    const rows = (data.roots || []).map((r) => `
      <div class="files-root">
        <span class="files-root-name">${icon(r.kind === "dir" ? "folder" : "fileText", { size: 15 })} ${esc(r.path)}</span>
        <span class="files-root-stats mono">${status.indexed ?? 0}/${status.total ?? 0} indexed${status.stale ? ` · ${status.stale} stale` : ""}</span>
        ${r.kind === "dir" ? `<button class="files-open" data-path="${esc(r.path)}">Open</button>` : ""}
        <button class="files-reindex" data-path="${esc(r.path)}">Reindex</button>
        <button class="files-remove" data-path="${esc(r.path)}">Remove</button>
      </div>`).join("");
    rootsEl.innerHTML = rows || `<p class="files-empty">No files registered yet.</p>`;
    rootsEl.querySelectorAll(".files-open").forEach((b) => {
      b.onclick = async () => {
        try {
          const card = await ctx.api.openFolder({ path: b.dataset.path });
          ctx.store.set({ view: "gallery", gallery: { type: "gallery", ...card } });
        } catch { /* ignore */ }
      };
    });
    rootsEl.querySelectorAll(".files-reindex").forEach((b) => {
      b.onclick = async () => { await ctx.api.reindexFiles(b.dataset.path); poll(); };
    });
    rootsEl.querySelectorAll(".files-remove").forEach((b) => {
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

  root.querySelector(".files-add").addEventListener("submit", (e) => {
    e.preventDefault();
    const path = pathInput.value.trim();
    if (!path) return;
    pathInput.value = "";
    addPath(path);
  });

  render();
}
