import { mount as chat } from "./views/chat.js";
import { mount as timeline } from "./views/timeline.js";
import { mount as sources } from "./views/sources.js";
import { mount as review } from "./views/review.js";

const VIEWS = { chat, timeline, sources, review };
const store = { transcript: [], _onChange: null, pendingToken: null };
const touch = () => store._onChange && store._onChange();

let ws = null;
function connect() {
  const conn = document.getElementById("conn");
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => (conn.textContent = "connected");
  ws.onclose = () => { conn.textContent = "disconnected"; setTimeout(connect, 1500); };
  ws.onerror = () => (conn.textContent = "error");
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "error") {
      store.transcript.push({ role: "io", text: "⚠ " + m.message, shape: "text" });
    } else {
      store.transcript.push({ role: "io", text: m.message, shape: "text" });
      store.pendingToken = m.pending_token || null;
    }
    touch();
  };
}

function send(text) {
  store.transcript.push({ role: "user", text, shape: "text" });
  touch();
  const frame = { text, source: "text" };
  if (store.pendingToken && /^(y|yes)$/i.test(text)) frame.confirm_token = store.pendingToken;
  ws.send(JSON.stringify(frame));
}

function route() {
  const name = location.hash.replace(/^#\//, "") || "chat";
  const view = VIEWS[name] || chat;
  for (const a of document.querySelectorAll("#nav a"))
    a.classList.toggle("active", a.getAttribute("href") === `#/${name}`);
  view(document.getElementById("view"), store, send);
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => { connect(); route(); });
