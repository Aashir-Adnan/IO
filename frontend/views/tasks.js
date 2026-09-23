import { icon } from "../vendor/icons.js";
import { mountTodo } from "../widgets/todo.js";

// The small always-on-top tasks window (route #tasks): only the pending-task
// list, with its own close button (the window is frameless).
export function mount(root, ctx) {
  root.innerHTML = `
    <section class="tw">
      <header class="tw-h">
        <span class="tw-t">Pending tasks</span>
        <button class="tw-x" type="button" aria-label="Close">${icon("x", { size: 14 })}</button>
      </header>
      <div class="tw-b"></div>
    </section>`;
  root.querySelector(".tw-x").onclick = () => {
    try { window.pywebview.api.close(); } catch { window.close(); }
  };
  root._cleanup = mountTodo(root.querySelector(".tw-b"), ctx, { size: "L" });
}
