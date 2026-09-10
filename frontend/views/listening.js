import { Orb } from "../components/orb.js";
import { WavRecorder } from "../vendor/recorder.js";

export async function mount(root, ctx) {
  const status = document.getElementById("status");
  if (status) status.innerHTML = `<span class="mic-live">● MIC LIVE</span>`;

  root.innerHTML = `
    <section class="listening">
      <div class="listening-head">
        <div class="mono kicker accent">LISTENING</div>
        <div class="statrow mono">
          <span><b id="l-gain">-∞</b> GAIN</span><span class="sep">·</span>
          <span><b>ON</b> VAD</span><span class="sep">·</span>
          <span><b id="l-elapsed">0:00</b> ELAPSED</span>
        </div>
      </div>
      <div class="listening-orb"></div>
      <div class="listening-hint mono">RELEASE <b>ALT SPACE</b> TO SEND · <b>ESC</b> TO CANCEL</div>
    </section>`;

  const orb = Orb(root.querySelector(".listening-orb"), { mode: "listening", size: 300 });
  const gainEl = root.querySelector("#l-gain");
  const elapsedEl = root.querySelector("#l-elapsed");

  const rec = new WavRecorder();
  let running = true;
  const t0 = performance.now();

  try {
    await rec.start();
  } catch (e) {
    inlineError(root, "microphone unavailable");
    setTimeout(() => ctx.goto("standby"), 1200);
    return;
  }

  const tick = () => {
    if (!running) return;
    const lvl = rec.level();
    orb.setLevel(0.2 + lvl * 0.8);
    gainEl.textContent = lvl > 0.001 ? `${Math.round(20 * Math.log10(lvl))} dB` : "-∞";
    const s = Math.floor((performance.now() - t0) / 1000);
    elapsedEl.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  const finish = async (send) => {
    if (!running) return;
    running = false;
    cleanup();
    const blob = await rec.stop();
    if (!send) { ctx.goto("standby"); return; }
    ctx.goto("conversation");
    try {
      const reply = await ctx.api.sendVoice(blob, {
        conversationId: ctx.store.get().conversationId,
        speak: ctx.store.get().autoSpeak !== "never",
      });
      ctx.store.set({ conversationId: reply.conversation_id });
      const conv = await import("./conversation.js");
      if (reply.transcript) conv.appendUserLine(ctx, reply.transcript);
      ctx.onTurn && ctx.onTurn({ ...reply, type: "answer" });
      if (reply.audio_b64 && ctx.store.get().autoSpeak !== "never") ctx.speak(reply.audio_b64);
    } catch (e) {
      ctx.goto("standby");
    }
  };

  const onKeyUp = (e) => { if (e.code === "Space") finish(true); };
  const onKeyDown = (e) => {
    if (e.key === "Escape") finish(false);
    if (e.code === "Space" && e.altKey) finish(true);
  };
  document.addEventListener("keyup", onKeyUp);
  document.addEventListener("keydown", onKeyDown);
  orb.el.style.cursor = "pointer";
  orb.el.addEventListener("click", () => finish(true));

  function cleanup() {
    document.removeEventListener("keyup", onKeyUp);
    document.removeEventListener("keydown", onKeyDown);
  }
  root._cleanup = cleanup;
}

function inlineError(root, msg) {
  const d = document.createElement("div");
  d.className = "listening-err";
  d.textContent = msg;
  root.appendChild(d);
}
