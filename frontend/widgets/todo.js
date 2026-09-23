import { icon } from "../vendor/icons.js";
import { esc } from "./util.js";

const GROUPS = [["overdue", "Overdue"], ["today", "Today"], ["upcoming", "Upcoming"], ["none", "Someday"]];

// The pending-tasks list: the To-do widget's body and the whole of the small
// tasks window. Ticking a circle completes the task through PATCH /record.
export function mountTodo(el, ctx, { size = "M" } = {}) {
  let tasks = [], err = null, alive = true;
  el.innerHTML = `<div class="todo size-${size}"></div>`;
  const root = el.firstElementChild;

  const paint = () => {
    if (!alive) return;
    const overdue = tasks.filter((t) => t.group === "overdue").length;
    if (err && !tasks.length) { root.innerHTML = `<p class="w-note">${esc(err)}</p>`; return; }
    if (!tasks.length) {
      root.innerHTML = `<div class="w-empty">${icon("checkCircle", { size: 22 })}<span>Nothing pending</span></div>`;
      return;
    }
    const head = `<div class="todo-count"><b>${tasks.length}</b> open${
      overdue ? ` · <span class="bad">${overdue} overdue</span>` : ""}</div>`;
    const small = size === "S";                 // 1x1: the count and the next task only
    const shown = small ? tasks.slice(0, 1) : tasks;
    const rows = GROUPS.map(([g, label]) => {
      const items = shown.filter((t) => t.group === g);
      if (!items.length) return "";
      return (small ? "" : `<div class="todo-group">${esc(label)}</div>`) + items.map((t) => `
        <div class="todo-row" data-id="${t.id}">
          <button class="todo-check" type="button" aria-label="Mark done">${icon("circle", { size: 17 })}</button>
          <span class="todo-title">${esc(t.title)}</span>
          ${t.due_label ? `<span class="todo-due ${t.group === "overdue" ? "bad" : ""}">${esc(t.due_label)}</span>` : ""}
        </div>`).join("");
    }).join("");
    root.innerHTML = head + `<div class="todo-list">${rows}</div>`;
  };

  root.addEventListener("click", async (e) => {
    const btn = e.target.closest(".todo-check");
    if (!btn) return;
    const row = btn.closest(".todo-row");
    const id = +row.dataset.id;
    row.classList.add("done");
    btn.innerHTML = icon("checkCircle", { size: 17 });
    try {
      await ctx.api.editRecord(id, { status: "done" });
      setTimeout(() => { tasks = tasks.filter((t) => t.id !== id); paint(); }, 350);
    } catch {
      row.classList.remove("done");
      btn.innerHTML = icon("circle", { size: 17 });
    }
  });

  const load = async () => {
    try { tasks = await ctx.api.tasks(); err = null; }
    catch { err = "Couldn't load tasks."; }
    paint();
  };
  load();
  const timer = setInterval(load, 15000);
  return () => { alive = false; clearInterval(timer); };
}
