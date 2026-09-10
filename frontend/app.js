import { createStore } from "./state.js";
import { Api } from "./api.js";
import { icon } from "./vendor/icons.js";
import { mount as mountStandby } from "./views/standby.js";
import { mount as mountListening } from "./views/listening.js";
import { mount as mountConversation } from "./views/conversation.js";
import { mount as mountLibrary } from "./views/library.js";
import { mount as mountRecords } from "./views/records.js";
import { Settings } from "./components/settings.js";

const VIEWS = {
  standby: mountStandby,
  talk: mountListening,
  conversation: mountConversation,
  library: mountLibrary,
  records: mountRecords,
  // legacy aliases — the library view covers both
  gallery: mountLibrary,
  files: mountLibrary,
};

const store = createStore({
  view: "standby",
  conversationId: null,
  conversationTitle: null,
  transcript: [],
  busy: false,
  autoSpeak: "voice",
  voiceOk: false,
  voiceReason: null,
  sttStreaming: false,
  sttProvider: "whisper",
  connection: "connecting",
  typingCps: 45,
  minThinkMs: 600,
  gallery: null,
});

const api = Api("");
let ws;
let currentAudio = null;
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
};

function handleTurn(frame) {
  const gc = (frame.cards || []).find((c) => c.type === "gallery");
  if (gc) { store.set({ view: "library", gallery: gc }); return; }
  ctx.onTurn && ctx.onTurn(frame);
}
ctx.handleTurn = handleTurn;

let viewAnimTimer = null;
function route() {
  const view = document.getElementById("view");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const mount = () => {
    if (typeof view._cleanup === "function") {
      try { view._cleanup(); } catch { /* ignore */ }
    }
    view._cleanup = null;
    view.classList.remove("leaving");
    view.innerHTML = "";
    const status = document.getElementById("status");
    if (status) status.innerHTML = "";
    stopAudio();
    const name = store.get().view;
    (VIEWS[name] || VIEWS.standby)(view, ctx);
    document.getElementById("win").dataset.view = name;
    if (!reduce) {
      view.classList.add("entering");
      clearTimeout(viewAnimTimer);
      viewAnimTimer = setTimeout(() => view.classList.remove("entering"), 720);
    }
  };

  if (reduce || !view.firstElementChild) { mount(); return; }
  view.classList.add("leaving");
  setTimeout(mount, 120);
}

let lastView = store.get().view;
store.subscribe((s) => {
  if (s.view !== lastView) { lastView = s.view; route(); }
});

// --- frameless pywebview window controls --------------------------------
function wv() { return window.pywebview && window.pywebview.api; }

const winMin = document.getElementById("win-min");
const winFull = document.getElementById("win-full");
const winClose = document.getElementById("win-close");
winMin.innerHTML = icon("minus", { size: 14 });
winClose.innerHTML = icon("x", { size: 14 });

function setFullscreen(on) {
  document.documentElement.dataset.fullscreen = on ? "1" : "";
  winFull.innerHTML = icon(on ? "cornersIn" : "cornersOut", { size: 13 });
  winFull.title = on ? "Exit fullscreen" : "Fullscreen";
}
setFullscreen(false);

winMin.onclick = () => wv() && wv().minimize();
winClose.onclick = () => (wv() ? wv().close() : window.close());
async function toggleFull() {
  if (!wv()) return;
  try { setFullscreen(await wv().toggle_fullscreen()); }
  catch { /* older api: assume it flipped */ setFullscreen(document.documentElement.dataset.fullscreen !== "1"); }
}
winFull.onclick = toggleFull;

document.getElementById("gear").innerHTML = icon("gear", { size: 16 });
document.getElementById("gear").onclick = () => settings.toggle();
document.getElementById("memory").innerHTML = icon("brain", { size: 16 });
document.getElementById("memory").onclick = () =>
  store.set({ view: store.get().view === "records" ? "standby" : "records" });

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    stopAudio();
    if (!document.getElementById("settings").hidden) { settings.close(); return; }
    if (store.get().view !== "standby") store.set({ view: "standby" });
    return;
  }
  // Alt+Enter — toggle fullscreen (Alt+Space stays reserved for voice)
  if (e.altKey && (e.key === "Enter" || e.code === "NumpadEnter")) {
    e.preventDefault();
    toggleFull();
  }
});

async function applyWindowEffects() {
  try {
    const eff = wv() && wv().effects ? await wv().effects() : null;
    document.documentElement.dataset.acrylic = eff && eff.acrylic ? "1" : "0";
  } catch { document.documentElement.dataset.acrylic = "0"; }
  try {
    if (wv() && wv().is_fullscreen) setFullscreen(await wv().is_fullscreen());
  } catch { /* keep current */ }
}

window.addEventListener("DOMContentLoaded", async () => {
  window.__ctx = ctx;
  applyWindowEffects();
  setTimeout(applyWindowEffects, 800);   // the backdrop is applied on 'shown'
  settings = Settings(
    document.getElementById("settings"),
    document.getElementById("settings-scrim"),
    ctx,
  );
  ws = api.connectWs((frame) => {
    if (frame.type === "_open") store.set({ connection: "connected" });
    else if (frame.type === "_close") store.set({ connection: "disconnected" });
    else if (frame.type === "progress") ctx.onProgress && ctx.onProgress(frame);
    else if (frame.type === "answer") handleTurn(frame);
  });
  try {
    const vh = await api.voiceHealth();
    // whisper is enough — the Piper voice self-downloads on the first spoken reply
    store.set({ voiceOk: !!vh.whisper, voiceReason: vh.reason || null });
  } catch { /* keep voiceOk false */ }
  try {
    const stt = await api.sttMode();
    // real-time streaming still needs a working mic; voiceOk from whisper is
    // the batch fallback, so treat either as "voice usable"
    store.set({
      sttStreaming: !!stt.streaming,
      sttProvider: stt.provider || "whisper",
      voiceOk: store.get().voiceOk || !!stt.streaming,
    });
  } catch { /* keep defaults */ }
  try {
    const convs = await api.conversations();
    if (convs[0]) store.set({ conversationId: convs[0].id, conversationTitle: convs[0].title || null });
  } catch { /* fresh */ }
  route();
});
