// Memory browser — every record IO has stored, editable and deletable.
// The place to clean up bad / misunderstood extractions.
import { icon } from "../vendor/icons.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
const KIND_GLYPH = {
  event: "clockCounterClockwise", task: "listChecks", chore: "listChecks",
  note: "fileText", fact: "fileText", habit: "clockCounterClockwise",
};
const whenText = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
};

export function mount(root, ctx) {
  const status = document.getElementById("status");
  if (status) status.innerHTML = `<span class="live">ON DEVICE</span><span id="rec-count">MEMORY</span>`;

  root.innerHTML = `
    <section class="records">
      <div class="records-head">
        <button class="records-back" aria-label="Back to chat">${icon("chatDots", { size: 18 })}</button>
        <h1>Memory</h1>
        <span class="records-count mono"></span>
        <div class="records-filters"></div>
      </div>
      <div class="records-list"></div>
    </section>`;

  root.querySelector(".records-back").onclick = () => ctx.goto("conversation");
  const listEl = root.querySelector(".records-list");
  const filtersEl = root.querySelector(".records-filters");
  const countEl = root.querySelector(".records-count");

  let all = [];
  let domain = null;

  function render() {
    const rows = domain ? all.filter((r) => (r.domain || "—") === domain) : all;
    countEl.textContent = `${rows.length} of ${all.length}`;

    const domains = [...new Set(all.map((r) => r.domain || "—"))].sort();
    filtersEl.innerHTML =
      `<button class="rec-filter${domain === null ? " on" : ""}" data-d="">all</button>` +
      domains.map((d) => `<button class="rec-filter${domain === d ? " on" : ""}" data-d="${esc(d)}">${esc(d)}</button>`).join("");
    filtersEl.querySelectorAll(".rec-filter").forEach((b) => {
      b.onclick = () => { domain = b.dataset.d || null; render(); };
    });

    if (!rows.length) {
      listEl.innerHTML = `<div class="records-empty">Nothing stored${domain ? " in this domain" : " yet"}.</div>`;
      return;
    }
    listEl.innerHTML = "";
    for (const r of rows) listEl.appendChild(rowEl(r));
  }

  function rowEl(r) {
    const row = document.createElement("div");
    row.className = "record-row";
    row.dataset.id = r.id;
    const glyph = KIND_GLYPH[r.kind] || "circle";
    row.innerHTML = `
      <span class="record-glyph">${icon(glyph, { size: 15 })}</span>
      <div class="record-main">
        <div class="record-title" contenteditable="plaintext-only" spellcheck="false">${esc(r.title)}</div>
        <div class="record-meta">
          <span class="record-tag">${esc([r.kind, r.domain].filter(Boolean).join(" · "))}</span>
          <button class="record-when" title="Edit date">${r.when ? whenText(r.when) : "+ date"}</button>
          ${(r.entities || []).map((e) =>
            `<button class="record-chip${e.etype === "person" ? " person" : ""}" data-etype="${e.etype}" data-id="${e.id}">${esc(e.name)}</button>`).join("")}
        </div>
      </div>
      <button class="record-del" aria-label="Delete">${icon("trash", { size: 15 })}</button>`;

    const title = row.querySelector(".record-title");
    title.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } });
    title.addEventListener("blur", async () => {
      const t = title.textContent.trim();
      if (!t || t === r.title) { title.textContent = r.title; return; }
      try { const u = await ctx.api.editRecord(r.id, { title: t }); r.title = u.title; }
      catch { title.textContent = r.title; }
    });

    row.querySelector(".record-when").onclick = async () => {
      const phrase = window.prompt("When? (e.g. 'the 10th of september', 'tomorrow', or blank to clear)", "");
      if (phrase === null) return;
      try {
        const u = await ctx.api.editRecord(r.id, { when_phrase: phrase });
        r.when = u.when;
        row.querySelector(".record-when").textContent = r.when ? whenText(r.when) : "+ date";
      } catch (e) { row.querySelector(".record-when").textContent = "bad date"; setTimeout(render, 900); }
    };

    row.querySelectorAll(".record-chip[data-etype]").forEach((c) => {
      c.onclick = () => ctx.openInspector && ctx.openInspector(c.dataset.etype, +c.dataset.id);
    });

    const del = row.querySelector(".record-del");
    del.onclick = () => {
      if (!row.classList.contains("confirm")) {
        row.classList.add("confirm");
        del.innerHTML = "delete?";
        setTimeout(() => { row.classList.remove("confirm"); del.innerHTML = icon("trash", { size: 15 }); }, 3000);
        return;
      }
      ctx.api.deleteRecord(r.id).then(() => {
        all = all.filter((x) => x.id !== r.id);
        row.remove();
        render();
      }).catch(() => { row.classList.remove("confirm"); del.innerHTML = icon("trash", { size: 15 }); });
    };
    return row;
  }

  ctx.api.records().then((d) => { all = d; render(); })
    .catch(() => { listEl.innerHTML = `<div class="records-empty">Couldn't load records.</div>`; });
}
