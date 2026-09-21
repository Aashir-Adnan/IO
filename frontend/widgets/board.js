import { icon } from "../vendor/icons.js";
import { COLS, span, place, move, resize, remove, normalize } from "./layout.js";
import { WIDGETS, TYPES, newId, defaultLayout } from "./index.js";
import { debounce, esc } from "./util.js";

// The home-screen widget board: a snap grid of premade widgets. Edit mode lets
// the user drag cards between cells, resize (S/M/L), remove, and add widgets.
// Layout and per-widget settings persist through GET/PUT /widgets.
export function mountBoard(host, ctx) {
  let layout = [], settings = {}, editing = false, alive = true, ready = false;
  const cleanups = [];
  host.classList.add("wb");
  host.innerHTML = `
    <div class="wb-bar" hidden>
      <span class="wb-bar-l">Add</span>
      ${TYPES.map((t) => `<button type="button" class="wb-add" data-type="${t}">${icon("plus", { size: 13 })}${esc(WIDGETS[t].title)}</button>`).join("")}
      <span class="wb-spacer"></span>
      <button type="button" class="wb-reset">Reset</button>
      <button type="button" class="wb-done">Done</button>
    </div>
    <div class="wb-grid"></div>`;
  const bar = host.querySelector(".wb-bar"), grid = host.querySelector(".wb-grid");

  const save = debounce(() => {
    const doc = { layout: layout.map(({ id, type, size, col, row }) => ({ id, type, size, col, row })), settings };
    ctx.api.saveWidgets(doc).catch(() => { /* next edit retries */ });
  }, 400);

  const unmountAll = () => { while (cleanups.length) { try { cleanups.pop()(); } catch { /* ignore */ } } };

  const render = () => {
    unmountAll();
    grid.innerHTML = "";
    grid.classList.toggle("editing", editing);
    bar.hidden = !editing;
    host.classList.toggle("empty", !layout.length && !editing);
    for (const it of layout) {
      const def = WIDGETS[it.type];
      if (!def) continue;
      const { w, h } = span(it.size);
      const card = document.createElement("div");
      card.className = `wcard size-${it.size}`;
      card.dataset.id = it.id;
      card.style.gridColumn = `${it.col + 1} / span ${w}`;
      card.style.gridRow = `${it.row + 1} / span ${h}`;
      card.innerHTML = `
        <div class="wcard-h"><span class="wcard-t">${esc(def.title)}</span><span class="wcard-tools"></span></div>
        <div class="wcard-b"></div>`;
      const tools = card.querySelector(".wcard-tools");
      if (def.action && !editing) {
        tools.innerHTML = `<button type="button" class="wcard-act" title="${esc(def.action.title)}" aria-label="${esc(def.action.title)}">${icon(def.action.icon, { size: 14 })}</button>`;
        tools.firstElementChild.onclick = def.action.run;
      }
      if (editing) {
        tools.innerHTML = `
          <span class="wseg">${["S", "M", "L"].map((s) => `<button type="button" data-size="${s}" class="${s === it.size ? "on" : ""}">${s}</button>`).join("")}</span>
          <button type="button" class="wcard-x" aria-label="Remove">${icon("x", { size: 13 })}</button>`;
        tools.querySelectorAll("[data-size]").forEach((b) => b.onclick = () => change(resize(layout, it.id, b.dataset.size)));
        tools.querySelector(".wcard-x").onclick = () => change(remove(layout, it.id));
        card.draggable = true;
        card.addEventListener("dragstart", (e) => {
          e.dataTransfer.setData("text/plain", it.id);
          e.dataTransfer.effectAllowed = "move";
          card.classList.add("dragging");
        });
        card.addEventListener("dragend", () => card.classList.remove("dragging"));
      }
      grid.appendChild(card);
      const mount = def.mount(card.querySelector(".wcard-b"), ctx, {
        size: it.size, id: it.id,
        settings: {
          get: () => settings[it.id] || {},
          set: (v) => { settings[it.id] = v; save(); },
        },
      });
      if (typeof mount === "function") cleanups.push(mount);
    }
  };

  const change = (next) => { layout = next; render(); save(); };

  // drop target: which grid cell is under the pointer
  const cellAt = (e) => {
    const r = grid.getBoundingClientRect(), cs = getComputedStyle(grid);
    const gap = parseFloat(cs.columnGap) || 12, cellH = parseFloat(cs.getPropertyValue("--wb-cell")) || 118;
    const cellW = (r.width - gap * (COLS - 1)) / COLS;
    return {
      col: Math.max(0, Math.min(COLS - 1, Math.floor((e.clientX - r.left) / (cellW + gap)))),
      row: Math.max(0, Math.floor((e.clientY - r.top) / (cellH + gap))),
    };
  };
  grid.addEventListener("dragover", (e) => { if (editing) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } });
  grid.addEventListener("drop", (e) => {
    if (!editing) return;
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    if (!layout.some((i) => i.id === id)) return;
    const { col, row } = cellAt(e);
    change(move(layout, id, col, row));
  });

  bar.addEventListener("click", (e) => {
    const add = e.target.closest(".wb-add");
    if (add) return change(place(layout, { id: newId(add.dataset.type), type: add.dataset.type, size: "M" }));
    if (e.target.closest(".wb-reset")) { settings = {}; return change(defaultLayout()); }
    if (e.target.closest(".wb-done")) api.setEditing(false);
  });

  const api = {
    get editing() { return editing; },
    setEditing(on) {
      editing = !!on; render();
      host.dispatchEvent(new CustomEvent("wb-edit", { detail: editing }));
    },
    toggleEdit() { api.setEditing(!editing); },
    destroy() { alive = false; unmountAll(); save.flush?.(); },
  };

  ctx.api.widgets().then((doc) => {
    if (!alive) return;
    settings = doc.settings || {};
    layout = normalize(doc.layout || defaultLayout());
    ready = true;
    render();
    if (!doc.layout) save();          // first run: keep the premade layout
  }).catch(() => { if (alive) { layout = defaultLayout(); render(); } });

  return api;
}
