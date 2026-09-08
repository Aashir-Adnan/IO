import { userBubble, ioBubble } from "../components/bubble.js";
import { renderCard } from "../components/card.js";
import { renderMarkdown } from "../vendor/markdown.js";
import { revealText } from "../typing.js";
import { Composer } from "../components/composer.js";
import { mountInspector, clearInspector } from "../components/inspector.js";

let session = { recalls: 0, writes: 0 };

export async function mount(root, ctx) {
  root.innerHTML = `
    <section class="convo">
      <div class="convo-main">
        <div class="thread" id="thread"></div>
        <div class="convo-composer"></div>
      </div>
      <aside class="inspector-slot" id="inspector"></aside>
    </section>`;

  const thread = root.querySelector("#thread");
  const status = document.getElementById("status");
  const setStatus = () => {
    if (status) status.textContent = `${session.recalls} RECALLS · ${session.writes} WRITES`;
  };
  setStatus();

  ctx.openInspector = async (etype, id) => {
    try {
      const panel = await ctx.api.entity(etype, id);
      mountInspector(root.querySelector("#inspector"), panel);
    } catch { /* ignore */ }
  };

  // render whatever transcript we already have (history hydration or prior turns)
  for (const m of ctx.store.get().transcript) {
    if (m.role === "user") thread.appendChild(userBubble(m.text));
    else appendIoInstant(thread, m, ctx);
  }
  scroll(thread);

  ctx.onTurn = (frame) => renderAssistant(thread, frame, ctx, setStatus);

  const composer = Composer(root.querySelector(".convo-composer"), {
    compact: true,
    placeholder: "Reply to IO",
    onSend: (text) => sendTurn(ctx, text),
    onMic: () => ctx.store.get().voiceOk && ctx.goto("talk"),
  });
  composer.focus();
  ctx._composer = composer;
}

export function sendTurn(ctx, text, { confirmToken } = {}) {
  const thread = document.getElementById("thread");
  if (thread) { thread.appendChild(userBubble(text)); scroll(thread); }
  ctx.store.update((s) => ({ transcript: [...s.transcript, { role: "user", text }] }));

  const frame = { text, source: "text", conversation_id: ctx.store.get().conversationId };
  if (confirmToken) frame.confirm_token = confirmToken;

  const viaWs = ctx.ws && ctx.ws.send(frame);
  if (!viaWs) {
    ctx.api.sendText({ text, conversationId: frame.conversation_id, confirmToken })
      .then((r) => (ctx.handleTurn || ctx.onTurn)({ ...r, type: "answer" }))
      .catch(() => renderError(thread));
  }
}

function renderAssistant(thread, frame, ctx, setStatus) {
  if (frame.type === "error") { renderError(thread, frame.message); return; }
  ctx.store.set({ conversationId: frame.conversation_id });
  if (frame.intent === "query") session.recalls++;
  if (frame.kind === "ack") session.writes++;
  setStatus();

  const b = ioBubble();
  b.setStreaming(true);
  thread.appendChild(b.el);
  scroll(thread);

  const opts = {
    cps: ctx.store.get().typingCps,
    minThinkMs: ctx.store.get().minThinkMs,
    onProgress: () => scroll(thread),
    onDone: () => {
      b.body.innerHTML = frame.shape === "markdown" || frame.shape === "diagram"
        ? renderMarkdown(frame.text)
        : renderMarkdown(frame.text);
      b.setStreaming(false);
      renderCards(b, frame, ctx);
      openInspectorFor(frame, ctx);
      scroll(thread);
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
    bar.innerHTML = `<button class="btn btn-primary" data-yes>Yes</button><button class="btn" data-no>Rephrase</button>`;
    bar.querySelector("[data-yes]").onclick = () => { bar.remove(); sendTurn(ctx, "yes", { confirmToken: frame.pending_token }); };
    bar.querySelector("[data-no]").onclick = () => { bar.remove(); ctx._composer && ctx._composer.focus(); };
    b.actions.appendChild(bar);
  }
}

function renderCards(b, frame, ctx) {
  for (const c of frame.cards || []) b.cards.appendChild(renderCard(c, ctx));
  b.cards.classList.toggle("has", (frame.cards || []).length > 0);
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

function scroll(thread) { thread.scrollTop = thread.scrollHeight; }
