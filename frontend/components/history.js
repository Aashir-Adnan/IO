import { icon } from "../vendor/icons.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function groupLabel(iso) {
  const d = new Date(iso);
  const now = new Date();
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  if (sameDay(d, now)) return "TODAY";
  const y = new Date(now); y.setDate(y.getDate() - 1);
  if (sameDay(d, y)) return "YESTERDAY";
  return "EARLIER";
}

function relTime(iso) {
  const d = new Date(iso);
  const now = new Date();
  const mins = Math.round((now - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

// The persistent conversation rail inside the conversation view (mockup 3b).
// `onPick` fires after a chat is loaded into the store (the view is already
// mounted, so the thread has to re-hydrate itself).
export function HistoryList(el, ctx, { onPick } = {}) {
  async function render() {
    let convs = [];
    try { convs = await ctx.api.conversations(); } catch { /* offline */ }
    const active = ctx.store.get().conversationId;

    const groups = {};
    for (const c of convs) (groups[groupLabel(c.last_at)] ||= []).push(c);
    const order = ["TODAY", "YESTERDAY", "EARLIER"].filter((g) => groups[g]);

    el.innerHTML = `
      <div class="history-list">
        ${order.map((g) => `
          <div class="history-group">${g}</div>
          ${groups[g].map((c) => `
            <button class="history-item${c.id === active ? " on" : ""}" data-id="${c.id}">
              <div class="hi-title">${esc(c.title || "Untitled")}</div>
              <div class="hi-sub">${relTime(c.last_at)}${
                c.message_count ? ` · ${c.message_count} messages` : ""
              }</div>
            </button>`).join("")}
        `).join("") || `<div class="history-group">NO CHATS YET</div>`}
      </div>
      <button class="history-new">${icon("plus", { size: 14 })} New chat</button>`;

    el.querySelector(".history-new").onclick = async () => {
      try {
        const { conversation_id } = await ctx.api.newConversation();
        ctx.store.set({ conversationId: conversation_id, conversationTitle: null, transcript: [], view: "standby" });
      } catch { /* ignore */ }
    };
    el.querySelectorAll(".history-item").forEach((b) => {
      b.onclick = async () => {
        const id = +b.dataset.id;
        try {
          const { messages } = await ctx.api.conversation(id);
          const transcript = messages.slice().reverse().map((m) => ({
            role: m.role === "assistant" ? "io" : m.role,
            text: m.text, shape: "text", cards: [],
          }));
          const title = (el.querySelector(`.history-item[data-id="${id}"] .hi-title`) || {}).textContent;
          ctx.store.set({ conversationId: id, conversationTitle: title || null, transcript, view: "conversation" });
          render();
          onPick && onPick();
        } catch { /* ignore */ }
      };
    });
  }

  render();
  return { refresh: render };
}
