import { renderMarkdown } from "../vendor/markdown.js";

function groupLabel(iso) {
  const d = new Date(iso);
  const now = new Date();
  const day = (a, b) => a.toDateString() === b.toDateString();
  if (day(d, now)) return "Today";
  const y = new Date(now); y.setDate(y.getDate() - 1);
  if (day(d, y)) return "Yesterday";
  return "Earlier";
}

export function Drawer(el, ctx) {
  async function render() {
    let convs = [];
    try { convs = await ctx.api.conversations(); } catch { /* ignore */ }
    const active = ctx.store.get().conversationId;
    const groups = {};
    for (const c of convs) (groups[groupLabel(c.last_at)] ||= []).push(c);
    el.innerHTML = `
      <button class="drawer-new">+ New conversation</button>
      ${["Today", "Yesterday", "Earlier"].filter((g) => groups[g]).map((g) => `
        <div class="drawer-group mono">${g}</div>
        ${groups[g].map((c) => `
          <button class="drawer-item${c.id === active ? " on" : ""}" data-id="${c.id}">${escape(c.title || "Untitled")}</button>`).join("")}
      `).join("")}`;

    el.querySelector(".drawer-new").onclick = async () => {
      const { conversation_id } = await ctx.api.newConversation();
      ctx.store.set({ conversationId: conversation_id, transcript: [], view: "standby" });
      close();
    };
    el.querySelectorAll(".drawer-item").forEach((b) => {
      b.onclick = async () => {
        const id = +b.dataset.id;
        const { messages } = await ctx.api.conversation(id);
        const transcript = messages.slice().reverse().map((m) => ({
          role: m.role, text: m.text, shape: "text", cards: [],
        }));
        ctx.store.set({ conversationId: id, transcript, view: "conversation" });
        close();
      };
    });
  }
  function open() { el.hidden = false; render(); }
  function close() { el.hidden = true; }
  function toggle() { el.hidden ? open() : close(); }
  return { open, close, toggle, render };
}

function escape(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
