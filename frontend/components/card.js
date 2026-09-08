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
      <div class="task-row">
        ${icon(it.status === "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" })}
        <span class="task-t${it.status === "done" ? " done" : ""}">${escape(it.title)}</span>
        <span class="mono task-due">${it.due ? when(it.due).toUpperCase() : (it.status || "").toUpperCase()}</span>
      </div>`).join("")}</div>`;
  } else if (card.type === "sources") {
    el.className = "card-sources mono";
    el.innerHTML = `${icon("brain", { size: 13 })}<span>${card.count} ${card.count === 1 ? "MEMORY" : "MEMORIES"} USED</span>` +
      (card.labels || []).map((l) => `<span class="sep">·</span><span>${escape(l).toUpperCase()}</span>`).join("");
  }
  return el;
}

function escape(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
