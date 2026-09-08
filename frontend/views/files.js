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
          <input type="text" name="path" placeholder="Add a file or folder path" />
          <button type="submit">${icon("folders", { size: 16 })} Add</button>
        </form>
        <div class="files-msg" hidden></div>
      </header>
      <div class="files-roots"></div>
    </section>`;

  const rootsEl = root.querySelector(".files-roots");
  const msg = root.querySelector(".files-msg");
  let timer = null;

  async function render() {
    let data = { roots: [] };
    try { data = await ctx.api.files(); } catch { /* offline */ }
    let status = {};
    try { status = await ctx.api.filesStatus(); } catch { /* ignore */ }
    const rows = (data.roots || []).map((r) => `
      <div class="files-root">
        <span class="files-root-name">${icon(r.kind === "dir" ? "folder" : "fileText", { size: 15 })} ${esc(r.path)}</span>
        <span class="files-root-stats mono">${status.indexed ?? 0}/${status.total ?? 0} indexed${status.stale ? ` · ${status.stale} stale` : ""}</span>
        <button class="files-reindex" data-path="${esc(r.path)}">Reindex</button>
        <button class="files-remove" data-path="${esc(r.path)}">Remove</button>
      </div>`).join("");
    rootsEl.innerHTML = rows || `<p class="files-empty">No files registered yet.</p>`;
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

  root.querySelector(".files-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const path = e.target.path.value.trim();
    if (!path) return;
    try {
      const r = await ctx.api.registerFile(path);
      msg.hidden = false;
      msg.textContent = `Added — ${r.discovered} file(s), indexing…`;
      e.target.reset();
      poll();
    } catch {
      msg.hidden = false;
      msg.textContent = "Couldn't add that path (not allowed or not found).";
    }
  });

  render();
}
