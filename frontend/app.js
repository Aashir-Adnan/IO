import { createStore } from "./state.js";
import { Api } from "./api.js";
import { icon } from "./vendor/icons.js";
import { mount as mountStandby } from "./views/standby.js";
import { mount as mountListening } from "./views/listening.js";
import { mount as mountConversation } from "./views/conversation.js";
import { mount as mountFiles } from "./views/files.js";
import { mount as mountGallery } from "./views/gallery.js";
import { Drawer } from "./components/drawer.js";

const VIEWS = {
  standby: mountStandby,
  talk: mountListening,
  conversation: mountConversation,
  files: mountFiles,
  gallery: mountGallery,
};

const NAV = [
  { key: "waveform", nav: "standby", label: "Talk" },
  { key: "chatDots", nav: "conversation", label: "Conversation" },
  { key: "folders", nav: "files", label: "Files" },
  { key: "brain", nav: "memory", label: "Memory" },
  { key: "listChecks", nav: "tasks", label: "Tasks" },
  { key: "usersThree", nav: "people", label: "People" },
];

const store = createStore({
  view: "standby",
  conversationId: null,
  transcript: [],           // { role, text, shape, cards, streaming }
  busy: false,
  autoSpeak: "voice",
  voiceOk: false,
  voiceReason: null,
  connection: "connecting",
  typingCps: 45,
  minThinkMs: 600,
  gallery: null,
});

const api = Api("");
let ws;
let currentAudio = null;

function speak(audioB64) {
  stopAudio();
  const bytes = Uint8Array.from(atob(audioB64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  currentAudio = new Audio(url);
  currentAudio.play().catch(() => {});
  currentAudio.onended = () => { URL.revokeObjectURL(url); currentAudio = null; };
}
function stopAudio() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}

const ctx = { store, api, get ws() { return ws; }, speak, stopAudio, goto: (v) => store.set({ view: v }) };

function handleTurn(frame) {
  const gc = (frame.cards || []).find((c) => c.type === "gallery");
  if (gc) { store.set({ view: "gallery", gallery: gc }); return; }
  ctx.onTurn && ctx.onTurn(frame);
}
ctx.handleTurn = handleTurn;

function renderRail() {
  const el = document.getElementById("railnav");
  const active = store.get().view;
  el.innerHTML = NAV.map((n) =>
    `<button class="rail-btn${(n.nav === active || (n.nav === "standby" && active === "talk")) ? " on" : ""}" data-nav="${n.nav}" title="${n.label}" aria-label="${n.label}">${icon(n.key, { size: 19 })}</button>`
  ).join("");
  document.querySelector('.rail [data-nav="settings"]').innerHTML = icon("gear", { size: 19 });
}

function route() {
  renderRail();
  const name = store.get().view;
  const mount = VIEWS[name] || VIEWS.standby;
  const view = document.getElementById("view");
  view.innerHTML = "";
  stopAudio();
  mount(view, ctx);
}

let drawer;
document.getElementById("rail").addEventListener("click", (e) => {
  const b = e.target.closest("[data-nav]");
  if (!b) return;
  const nav = b.dataset.nav;
  if (nav === "conversation") { drawer.toggle(); return; }
  drawer.close();
  if (VIEWS[nav]) store.set({ view: nav });
  else store.set({ view: "conversation" });   // stub destinations land on the transcript
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") stopAudio();
});

let lastView = store.get().view;
store.subscribe((s) => {
  if (s.view !== lastView) { lastView = s.view; route(); }
});

window.addEventListener("DOMContentLoaded", async () => {
  window.__ctx = ctx;   // for the DOM smoke test
  drawer = Drawer(document.getElementById("drawer"), ctx);
  ws = api.connectWs((frame) => {
    if (frame.type === "_open") store.set({ connection: "connected" });
    else if (frame.type === "_close") store.set({ connection: "disconnected" });
    else if (frame.type === "answer") handleTurn(frame);
  });
  try {
    const vh = await api.voiceHealth();
    store.set({ voiceOk: !!(vh.whisper && vh.piper), voiceReason: vh.reason || null });
  } catch { /* keep voiceOk false */ }
  try {
    const convs = await api.conversations();
    if (convs[0]) store.set({ conversationId: convs[0].id });
  } catch { /* fresh */ }
  route();
});
