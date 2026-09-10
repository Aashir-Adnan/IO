import { userBubble, ioBubble } from "../components/bubble.js";
import { renderCard } from "../components/card.js";
import { renderMarkdown } from "../vendor/markdown.js";
import { revealText } from "../typing.js";
import { Composer } from "../components/composer.js";
import { mountInspector } from "../components/inspector.js";
import { HistoryList } from "../components/history.js";
import { icon } from "../vendor/icons.js";

let session = { recalls: 0, writes: 0 };

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export async function mount(root, ctx) {
  const status = document.getElementById("status");
  if (status) {
    status.innerHTML = `<span class="live">ON DEVICE</span><span id="convo-status">OLLAMA · IDLE</span>`;
  }

  root.innerHTML = `
    <section class="convo">
      <aside class="convo-side">
        <div class="convo-side-head">
          <button class="convo-back" aria-label="Back to standby">${icon("chevronLeft", { size: 16 })}</button>
          <div class="history-search">
            ${icon("magnifyingGlass", { size: 14 })}
            <input type="text" placeholder="Search chats and records" aria-label="Search" />
          </div>
        </div>
        <div class="history-mount"></div>
      </aside>
      <div class="convo-main">
        <div class="convo-head">
          <span class="ch-orb"></span>
          <span class="ch-title"></span>
          <span class="ch-meta mono"></span>
        </div>
        <div class="thread" id="thread"></div>
        <div class="convo-composer"></div>
      </div>
      <aside class="inspector-slot" id="inspector"></aside>
    </section>`;

  root.querySelector(".convo-back").onclick = () => ctx.goto("standby");

  const titleEl = root.querySelector(".ch-title");
  const metaEl = root.querySelector(".ch-meta");
  const setTitle = () => { titleEl.textContent = ctx.store.get().conversationTitle || "New conversation"; };
  const setMeta = () => {
    metaEl.textContent = session.recalls || session.writes
      ? `${session.recalls} RECALL${session.recalls === 1 ? "" : "S"} · ${session.writes} WRITE${session.writes === 1 ? "" : "S"}`
      : "";
  };
  setTitle();
  setMeta();

  // the search field is presentational for now — no backend search endpoint
  root.querySelector(".history-search input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") e.preventDefault();
  });

  const thread = root.querySelector("#thread");

  ctx.openInspector = async (etype, id) => {
    const slot = root.querySelector("#inspector");
    try {
      if (etype && typeof etype === "object") {
        // a file hit from a `files` card — show its text in the same panel
        const f = etype;
        mountInspector(slot, {
          name: f.title || "file", subtitle: "FILE",
          facts: [{ label: "CONTENT", text: (f.text || "").slice(0, 1400) }],
          confidence: 0, sourced_from: 0,
        });
        return;
      }
      mountInspector(slot, await ctx.api.entity(etype, id));
    } catch { /* ignore */ }
  };

  // render whatever transcript we already have (history hydration or prior turns)
  const hydrate = () => {
    thread.innerHTML = "";
    const t = ctx.store.get().transcript;
    if (!t.length) {
      thread.innerHTML = `<div class="thread-empty">Ask about anything you've told IO — people, plans, tasks, places.</div>`;
      return;
    }
    for (const m of t) {
      if (m.role === "user") thread.appendChild(userBubble(m.text));
      else appendIoInstant(thread, m, ctx);
    }
    scroll(thread);
  };
  hydrate();

  const history = HistoryList(root.querySelector(".history-mount"), ctx, {
    onPick: () => { hydrate(); setTitle(); setMeta(); },
  });

  ctx.onTurn = (frame) => renderAssistant(thread, frame, ctx, () => { setMeta(); history.refresh(); setTitle(); });
  ctx.onProgress = (f) => {
    addProgress(thread, f.stage, f.detail);
    ctx._composer && ctx._composer.setStatus(f.stage);
  };

  const composer = Composer(root.querySelector(".convo-composer"), {
    compact: true,
    placeholder: "Reply, or keep talking",
    onSend: (text) => sendTurn(ctx, text),
    onMic: () => ctx.store.get().voiceOk && ctx.goto("talk"),
  });
  composer.focus();
  ctx._composer = composer;

  // a turn queued from another view (standby ask bar, library "ask about this")
  if (ctx._pending) {
    const t = ctx._pending; ctx._pending = null;
    requestAnimationFrame(() => sendTurn(ctx, t));
  }
}

export function sendTurn(ctx, text, { confirmToken } = {}) {
  const thread = document.getElementById("thread");
  if (thread) { thread.appendChild(userBubble(text)); scroll(thread); }
  ctx.store.update((s) => ({ transcript: [...s.transcript, { role: "user", text }] }));

  const frame = { text, source: "text", conversation_id: ctx.store.get().conversationId };
  if (confirmToken) frame.confirm_token = confirmToken;

  const viaWs = ctx.ws && ctx.ws.send(frame);
  if (thread) startProgress(thread, viaWs);
  if (ctx._composer) {
    ctx._composer.setBusy(true);
    ctx._composer.setStatus(viaWs ? "Working on it…" : "Thinking…");
  }
  if (!viaWs) {
    ctx.api.sendText({ text, conversationId: frame.conversation_id, confirmToken })
      .then((r) => (ctx.handleTurn || ctx.onTurn)({ ...r, type: "answer" }))
      .catch(() => { clearProgress(thread); ctx._composer && ctx._composer.setBusy(false); renderError(thread); });
  }
}

// ── live "processing" strip while a turn is in flight ────────────────────
function startProgress(thread, live) {
  clearProgress(thread);
  const box = document.createElement("div");
  box.className = "turn-pending";
  box.dataset.t0 = String(Date.now());
  box.innerHTML = `
    <div class="tp-head">
      <span class="tp-spin"></span>
      <span class="tp-stage">${live ? "Working on it…" : "Thinking…"}</span>
      <span class="tp-elapsed mono"></span>
    </div>
    <div class="tp-log"></div>`;
  thread.appendChild(box);
  box._timer = setInterval(() => {
    const s = ((Date.now() - +box.dataset.t0) / 1000).toFixed(1);
    const el = box.querySelector(".tp-elapsed");
    if (el) el.textContent = s + "s";
  }, 100);
  scroll(thread);
}

function addProgress(thread, stage, detail) {
  let box = thread.querySelector(".turn-pending");
  if (!box) { startProgress(thread, true); box = thread.querySelector(".turn-pending"); }
  const st = box.querySelector(".tp-stage");
  if (st) st.textContent = stage;
  const line = document.createElement("div");
  line.className = "tp-line";
  line.innerHTML = `<span>${escHtml(stage)}</span>${detail ? `<span class="tp-detail">${escHtml(detail)}</span>` : ""}`;
  box.querySelector(".tp-log").appendChild(line);
  scroll(thread);
}

function clearProgress(thread) {
  const box = thread && thread.querySelector(".turn-pending");
  if (box) { clearInterval(box._timer); box.remove(); }
}

// hand the finished log to the answer bubble as a collapsed <details>
function takeProgressSteps(thread) {
  const box = thread && thread.querySelector(".turn-pending");
  if (!box) return null;
  clearInterval(box._timer);
  const lines = [...box.querySelectorAll(".tp-line")].map((l) => l.innerHTML);
  const secs = ((Date.now() - +box.dataset.t0) / 1000).toFixed(1);
  box.remove();
  if (!lines.length) return null;
  return { lines, secs };
}

function escHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderAssistant(thread, frame, ctx, after) {
  if (frame.type === "error") {
    clearProgress(thread);
    ctx._composer && ctx._composer.setBusy(false);
    renderError(thread, frame.message);
    return;
  }
  ctx.store.set({ conversationId: frame.conversation_id });
  if (frame.intent === "query") session.recalls++;
  if (frame.kind === "ack") session.writes++;

  const steps = takeProgressSteps(thread);
  ctx._composer && ctx._composer.setBusy(false);

  const b = ioBubble();
  b.setStreaming(true);
  thread.appendChild(b.el);
  if (steps) {
    const d = document.createElement("details");
    d.className = "turn-steps";
    d.innerHTML =
      `<summary>${steps.lines.length} step${steps.lines.length === 1 ? "" : "s"} · ${steps.secs}s</summary>` +
      `<div class="ts-log">${steps.lines.map((l) => `<div class="tp-line">${l}</div>`).join("")}</div>`;
    b.actions.appendChild(d);
  }
  scroll(thread);

  const opts = {
    cps: ctx.store.get().typingCps,
    minThinkMs: ctx.store.get().minThinkMs,
    onProgress: () => scroll(thread),
    onDone: () => {
      b.body.innerHTML = renderMarkdown(frame.text);
      b.setStreaming(false);
      renderCards(b, frame, ctx);
      openInspectorFor(frame, ctx);
      scroll(thread);
      after && after();
    },
  };
  const cancel = revealText(b.body, frame.text, opts);
  ctx._cancelReveal = cancel;
  ctx.store.update((s) => ({
    transcript: [...s.transcript, { role: "io", text: frame.text, shape: frame.shape, cards: frame.cards }],
  }));

  if (frame.pending_token) {
    const bar = document.createElement("div");
    bar.className = "gate-actions";
    const dismiss = () => { bar.remove(); ctx._composer && ctx._composer.focus(); };
    // gate-choice: a completion "which one do you mean?" gate lists numbered
    // candidates in frame.text ("1. call the dentist\n2. book the follow-up").
    // Two or more numbered lines → one button per candidate that answers with
    // its number; anything else is a plain store-confirmation Yes / Rephrase bar.
    const choices = [];
    const choiceRe = /^\s*(\d+)\.\s+(.+?)\s*$/gm;
    let m;
    while ((m = choiceRe.exec(frame.text))) choices.push({ n: m[1], title: m[2] });
    if (choices.length >= 2) {
      bar.innerHTML =
        choices
          .map((c) => `<button class="btn gate-choice" data-n="${esc(c.n)}">${esc(c.title)}</button>`)
          .join("") +
        `<button class="btn" data-no>Never mind</button>`;
      bar.querySelectorAll("[data-n]").forEach((btn) => {
        btn.onclick = () => {
          bar.remove();
          sendTurn(ctx, String(btn.dataset.n), { confirmToken: frame.pending_token });
        };
      });
      bar.querySelector("[data-no]").onclick = dismiss;
    } else {
      bar.innerHTML = `<button class="btn btn-primary" data-yes>Yes</button><button class="btn" data-no>Rephrase</button>`;
      bar.querySelector("[data-yes]").onclick = () => { bar.remove(); sendTurn(ctx, "yes", { confirmToken: frame.pending_token }); };
      bar.querySelector("[data-no]").onclick = dismiss;
    }
    b.actions.appendChild(bar);
  }
}

function renderCards(b, frame, ctx) {
  const cards = frame.cards || [];
  for (const c of cards) {
    if (c.type === "record") b.cards.appendChild(recordPills(c, ctx));
    else if (c.type === "gallery") { /* handled by the shell → library view */ }
    else b.cards.appendChild(renderCard(c, ctx));
  }
  b.cards.classList.toggle("has", b.cards.childElementCount > 0);
}

// mockup 3b renders a record as a row of small pills under the answer, not a card
function recordPills(card, ctx) {
  const wrap = document.createElement("div");
  wrap.className = "chips io-record-pills";
  const meta = [card.kind, card.domain].filter(Boolean).join(" · ");
  wrap.innerHTML =
    (meta ? `<span class="chip">${esc(meta)}</span>` : "") +
    (card.entities || []).map((e) =>
      `<button class="chip${e.etype === "person" ? " person" : ""}" data-etype="${e.etype}" data-id="${e.id}">${esc(e.name)}</button>`).join("");
  wrap.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".chip[data-etype]");
    if (btn && ctx.openInspector) ctx.openInspector(btn.dataset.etype, +btn.dataset.id);
  });
  return wrap;
}

function openInspectorFor(frame, ctx) {
  const rec = (frame.cards || []).find((c) => c.type === "record" && (c.entities || []).length);
  if (rec) ctx.openInspector(rec.entities[0].etype, rec.entities[0].id);
}

function appendIoInstant(thread, m, ctx) {
  const b = ioBubble();
  b.body.innerHTML = renderMarkdown(m.text);
  thread.appendChild(b.el);
  renderCards(b, { cards: m.cards }, ctx);
}

function renderError(thread, msg) {
  const d = document.createElement("div");
  d.className = "msg io error";
  d.textContent = "⚠ " + (msg || "something went wrong");
  thread.appendChild(d);
  scroll(thread);
}

export function appendUserLine(ctx, text) {
  const thread = document.getElementById("thread");
  if (thread) { thread.appendChild(userBubble(text)); scroll(thread); }
  ctx.store.update((s) => ({ transcript: [...s.transcript, { role: "user", text }] }));
}

function scroll(thread) {
  const empty = thread.querySelector(".thread-empty");
  if (empty) empty.remove();
  thread.scrollTop = thread.scrollHeight;
}
