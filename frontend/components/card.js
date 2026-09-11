import { icon } from "../vendor/icons.js";

const KIND_GLYPH = { event: "◆", task: "○", chore: "↻", note: "·" };

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const same = d.toDateString() === today.toDateString();
  return same
    ? "today · " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function wireChecks(root, ctx) {
  root.querySelectorAll(".task-check").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".task-row");
      const id = +row.dataset.id;
      const next = btn.getAttribute("aria-pressed") === "true" ? "open" : "done";
      row.querySelector(".task-t").classList.toggle("done", next === "done");
      btn.setAttribute("aria-pressed", String(next === "done"));
      btn.innerHTML = icon(next === "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" });
      try { await ctx.api.editRecord(id, { status: next }); }
      catch {
        btn.setAttribute("aria-pressed", String(next !== "done"));
        btn.innerHTML = icon(next !== "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" });
        row.querySelector(".task-t").classList.toggle("done", next !== "done");
      }
    });
  });
}

export function renderCard(card, ctx) {
  const el = document.createElement("div");
  el.className = "card card-" + card.type;
  el.dataset.type = card.type;

  if (card.type === "record") {
    const meta = [card.kind, card.domain].filter(Boolean).join(" · ").toUpperCase();
    const w = when(card.when || card.due);
    el.innerHTML = `
      <div class="card-h mono">
        <span class="card-glyph">${KIND_GLYPH[card.kind] || "·"}</span>
        <span>${meta}</span>${w ? `<span class="sep">—</span><span class="card-when">${w}</span>` : ""}
      </div>
      <div class="card-title">${escape(card.title)}</div>
      <div class="chips">${(card.entities || []).map((e) =>
        `<button class="chip${e.etype === "person" ? " person" : ""}" data-etype="${e.etype}" data-id="${e.id}">${escape(e.name)}</button>`).join("")}</div>`;
    if (ctx) {
      el.querySelector(".chips").addEventListener("click", (ev) => {
        const b = ev.target.closest(".chip");
        if (b) ctx.openInspector && ctx.openInspector(b.dataset.etype, +b.dataset.id);
      });
    }
  } else if (card.type === "tasklist") {
    el.innerHTML = `<div class="tasklist">${card.items.map((it) => `
      <div class="task-row" data-id="${it.record_id}">
        <button class="task-check" aria-pressed="${it.status === "done"}" aria-label="Toggle done">
          ${icon(it.status === "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" })}
        </button>
        <span class="task-t${it.status === "done" ? " done" : ""}">${escape(it.title)}</span>
        <span class="mono task-due">${it.due ? when(it.due).toUpperCase() : (it.status || "").toUpperCase()}</span>
      </div>`).join("")}</div>`;
    if (ctx) {
      wireChecks(el, ctx);
    }
  } else if (card.type === "collection") {
    el.className = "card card-collection";
    el.innerHTML = `
      <div class="cc-head">${escape(card.name)}<span class="mono">${card.items.length}</span></div>
      <div class="cc-list">${card.items.map((it) => `
        <div class="task-row" data-id="${it.record_id}">
          ${card.checkable ? `<button class="task-check" aria-pressed="${it.status === "done"}" aria-label="Toggle">${icon(it.status === "done" ? "checkCircle" : "circle", { size: 14 })}</button>` : `<span class="cc-dot"></span>`}
          <span class="task-t${it.status === "done" ? " done" : ""}">${escape(it.title)}</span>
        </div>`).join("")}</div>
      <form class="cc-add"><input type="text" placeholder="Add ${escape(card.item_noun || "item")}" /></form>`;
    if (ctx) {
      wireChecks(el, ctx);
      el.querySelector(".cc-add").addEventListener("submit", (e) => {
        e.preventDefault();
        const v = e.target.querySelector("input").value.trim();
        if (v && ctx.onAsk) { ctx.onAsk(`add ${v} to my ${card.name}`); e.target.reset(); }
      });
    }
  } else if (card.type === "sources") {
    el.className = "card-sources mono";
    el.innerHTML = `${icon("brain", { size: 13 })}<span>${card.count} ${card.count === 1 ? "MEMORY" : "MEMORIES"} USED</span>` +
      (card.labels || []).map((l) => `<span class="sep">·</span><span>${escape(l).toUpperCase()}</span>`).join("");
  } else if (card.type === "web") {
    el.className = "card card-web mono";
    const tier = card.cached ? "CACHED" : (card.tier === "a" ? "INSTANT" : "WEB");
    el.innerHTML =
      `${icon("globe", { size: 13 })}<span>${tier} · ${escape(card.kind || "").toUpperCase()}</span>` +
      (card.sources || []).map((s) => {
        let host = s.url;
        try { host = new URL(s.url).hostname.replace(/^www\./, ""); } catch { /* keep */ }
        return `<a class="web-src" href="${escape(s.url)}" target="_blank" rel="noopener" title="${escape(s.title)}">${escape(host)}</a>`;
      }).join("");
  } else if (card.type === "files") {
    el.className = "card card-files";
    el.innerHTML = `<div class="card-h mono"><span>${card.searched || 0} FILES SEARCHED</span></div>`;
    for (const h of card.hits || []) {
      const base = h.path.split(/[\\/]/).pop();
      const row = document.createElement("button");
      row.className = "file-row";
      row.innerHTML =
        `${icon(h.media_kind ? "file" : "fileText", { size: 14, cls: "file-i" })}` +
        `<span class="file-title">${escape(h.title || base)}</span>` +
        `<span class="file-path mono">${escape(h.path)}</span>` +
        `<span class="file-why">${escape(h.why || "")}</span>`;
      row.addEventListener("click", async () => {
        if (!ctx || !ctx.api) return;
        try {
          const doc = await ctx.api.fileContent(h.path);
          if (ctx.openInspector) {
            ctx.openInspector({ kind: "file", title: doc.title || h.path, text: doc.text });
          } else {
            const pre = document.createElement("pre");
            pre.className = "file-dump";
            pre.textContent = doc.text;
            el.appendChild(pre);
          }
        } catch { /* ignore */ }
      });
      el.appendChild(row);
    }
  }
  return el;
}

function escape(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
