import { createStore } from "./state.js";
import { Api } from "./api.js";
import { icon } from "./vendor/icons.js";
import { mount as mountStandby } from "./views/standby.js";
import { mount as mountListening } from "./views/listening.js";
import { mount as mountConversation } from "./views/conversation.js";
import { mount as mountGallery } from "./views/gallery.js";
import { Drawer } from "./components/drawer.js";
import { Settings } from "./components/settings.js";

const VIEWS = {
  standby: mountStandby,
  talk: mountListening,
  conversation: mountConversation,
  gallery: mountGallery,
};

const store = createStore({
  view: "standby",
  conversationId: null,
  transcript: [],
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
let drawer;
let settings;

function speak(audioB64) {
  if (!audioB64 || store.get().autoSpeak === "never") return;
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

const ctx = {
  store, api,
  get ws() { return ws; },
  speak, stopAudio,
  goto: (v) => store.set({ view: v }),
  openSettings: () => settings && settings.open(),
  toggleHistory: () => drawer && drawer.toggle(),
};

function handleTurn(frame) {
  const gc = (frame.cards || []).find((c) => c.type === "gallery");
  if (gc) { store.set({ view: "gallery", gallery: gc }); return; }
  ctx.onTurn && ctx.onTurn(frame);
}
ctx.handleTurn = handleTurn;

function route() {
  const view = document.getElementById("view");
  if (typeof view._cleanup === "function") {
    try { view._cleanup(); } catch { /* ignore */ }
  }
  view._cleanup = null;
  view.innerHTML = "";
  stopAudio();
  const name = store.get().view;
  (VIEWS[name] || VIEWS.standby)(view, ctx);
  document.getElementById("win").dataset.view = name;
}

let lastView = store.get().view;
store.subscribe((s) => {
  if (s.view !== lastView) { lastView = s.view; route(); }
});

// --- pywebview window controls -------------------------------------------
function wv() { return window.pywebview && window.pywebview.api; }
document.getElementById("win-min").onclick = () => wv() && wv().minimize();
document.getElementById("win-full").onclick = () => wv() && wv().toggle_fullscreen();
document.getElementById("win-close").onclick = () => wv() ? wv().close() : window.close();

document.getElementById("gear").innerHTML = icon("gear", { size: 18 });
document.getElementById("gear").onclick = () => settings.toggle();
document.getElementById("win-min").innerHTML = icon("minus", { size: 14 });
document.getElementById("win-full").innerHTML = icon("cornersOut", { size: 13 });
document.getElementById("win-close").innerHTML = icon("x", { size: 14 });

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    stopAudio();
    if (!document.getElementById("settings").hidden) { settings.close(); return; }
    if (store.get().view !== "standby") store.set({ view: "standby" });
  }
});

window.addEventListener("DOMContentLoaded", async () => {
  window.__ctx = ctx;
  drawer = Drawer(document.getElementById("drawer"), ctx);
  settings = Settings(
    document.getElementById("settings"),
    document.getElementById("settings-scrim"),
    ctx,
  );
  ws = api.connectWs((frame) => {
    if (frame.type === "_open") store.set({ connection: "connected" });
    else if (frame.type === "_close") store.set({ connection: "disconnected" });
    else if (frame.type === "answer") handleTurn(frame);
  });
  try {
    const vh = await api.voiceHealth();
    // whisper is enough — the Piper voice self-downloads on the first spoken reply
    store.set({ voiceOk: !!vh.whisper, voiceReason: vh.reason || null });
  } catch { /* keep voiceOk false */ }
  try {
    const convs = await api.conversations();
    if (convs[0]) store.set({ conversationId: convs[0].id });
  } catch { /* fresh */ }
  route();
});
