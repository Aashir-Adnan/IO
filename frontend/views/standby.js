import { Orb } from "../components/orb.js";
import { icon } from "../vendor/icons.js";
import { sendTurn } from "./conversation.js";
import { WavRecorder } from "../vendor/recorder.js";

function greet(clockIso) {
  const h = clockIso ? new Date(clockIso).getHours() : new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
const pad = (n) => String(n).padStart(2, "0");
const longDate = (d) => d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });

export function mount(root, ctx) {
  const status = document.getElementById("status");
  if (status) status.textContent = "LOCAL · ENCRYPTED";

  root.innerHTML = `
    <section class="standby">
      <div class="standby-stage">
        <div class="standby-orb"></div>
        <div class="standby-clock">
          <div class="clk-h"></div>
          <div class="clk-m"></div>
          <div class="clk-date"></div>
        </div>
      </div>
      <div class="standby-foot">
        <div class="standby-greet"></div>
        <div class="chips"></div>
        <form class="askbar">
          <button type="button" class="askbar-mic" aria-label="Voice">${icon("mic", { size: 17 })}</button>
          <input type="text" class="askbar-in" placeholder="Ask IO anything" autocomplete="off" />
          <button type="submit" class="askbar-send" aria-label="Send">${icon("arrowUp", { size: 17 })}</button>
        </form>
      </div>
    </section>`;

  const orb = Orb(root.querySelector(".standby-orb"), { mode: "standby", size: 460 });

  const hEl = root.querySelector(".clk-h");
  const mEl = root.querySelector(".clk-m");
  const dEl = root.querySelector(".clk-date");
  const tick = () => {
    const now = new Date();
    hEl.textContent = pad(now.getHours());
    mEl.textContent = pad(now.getMinutes());
    dEl.textContent = longDate(now);
  };
  tick();
  const timer = setInterval(tick, 10000);

  const input = root.querySelector(".askbar-in");
  const submit = (text) => {
    const v = (text ?? input.value).trim();
    if (!v) return;
    input.value = "";
    ctx.goto("conversation");
    sendTurn(ctx, v);
  };
  root.querySelector(".askbar").addEventListener("submit", (e) => { e.preventDefault(); submit(); });

  // voice input — record, transcribe, send
  let rec = null;
  const micBtn = root.querySelector(".askbar-mic");
  micBtn.addEventListener("click", async () => {
    if (rec) {
      micBtn.classList.remove("rec");
      const blob = await rec.stop(); rec = null;
      try {
        const { transcript } = await ctx.api.transcribeAudio(blob);
        if (transcript && transcript.trim()) submit(transcript);
      } catch { /* ignore */ }
      return;
    }
    if (!ctx.store.get().voiceOk) { ctx.openSettings(); return; }
    try { rec = new WavRecorder(); await rec.start(); micBtn.classList.add("rec"); }
    catch { rec = null; }
  });

  let data = { greeting_name: "there", stats: {}, chips: [] };
  ctx.api.standby().then((d) => {
    data = d;
    root.querySelector(".standby-greet").textContent =
      `${greet(data.stats && data.stats.clock)}, ${data.greeting_name}.`;
    const chips = root.querySelector(".chips");
    chips.innerHTML = (data.chips || []).map((c) =>
      `<button class="chip" type="button">${icon(c.icon === "list-checks" ? "listChecks" : c.icon === "users-three" ? "usersThree" : "circle", { size: 12 })}<span>${c.text}</span></button>`
    ).join("");
    chips.onclick = (e) => {
      const b = e.target.closest(".chip");
      if (b) submit(b.textContent.trim());
    };
  }).catch(() => { /* offline */ });

  const onKey = (e) => {
    if (e.code === "Space" && e.altKey && ctx.store.get().voiceOk) {
      e.preventDefault(); micBtn.click();
    }
  };
  document.addEventListener("keydown", onKey);
  setTimeout(() => input.focus(), 30);

  root._cleanup = () => {
    clearInterval(timer);
    document.removeEventListener("keydown", onKey);
    if (rec) { try { rec.stop(); } catch { /* ignore */ } }
    orb.destroy();
  };
}
