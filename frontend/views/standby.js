import { Orb } from "../components/orb.js";
import { icon } from "../vendor/icons.js";
import { createMic } from "../mic.js";

function greet(clockIso) {
  const h = clockIso ? new Date(clockIso).getHours() : new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
const pad = (n) => String(n).padStart(2, "0");
const weekday = (d) => d.toLocaleDateString([], { weekday: "long" }).toUpperCase();
const monthDay = (d) => d.toLocaleDateString([], { month: "long", day: "numeric" }).toUpperCase();
const mmss = (secs) => `${Math.floor(secs / 60)}:${pad(secs % 60)}`;

// Rotating placeholder — one example per feature so the ask bar reads as a
// chatbot prompt, not a search box.
const EXAMPLES = [
  "What are my tasks today?",
  "Open the folder called Downloads",
  "When did I last see Marcus?",
  "Whose birthday is coming up?",
  "What does my lease say about pets?",
  "I had coffee with Sana this morning",
  "Guess who I ran into at work",
  "How's my gym been going?",
  "Find the Granjur invoice",
];

export function mount(root, ctx) {
  const status = document.getElementById("status");
  if (status) {
    status.innerHTML = `<span class="live">ON DEVICE</span><span>${
      ctx.store.get().connection === "connected" ? "LOCAL · READY" : "LOCAL · ENCRYPTED"
    }</span>`;
  }

  root.innerHTML = `
    <section class="standby">
      <div class="standby-stage">
        <div class="standby-orb"></div>
        <div class="standby-clock">
          <div class="standby-clockrow">
            <div class="standby-time">
              <span class="clk-h"></span>
              <span class="clk-m"></span>
            </div>
            <div class="clk-when">
              <span class="clk-day"></span>
              <span class="clk-date"></span>
            </div>
          </div>
          <div class="hair"></div>
          <div class="standby-agenda"></div>
        </div>
      </div>
      <div class="standby-foot">
        <div class="standby-greet"></div>
        <form class="askbar">
          <button type="button" class="askbar-mic" aria-label="Voice">${icon("mic", { size: 18 })}</button>
          <textarea class="askbar-in" rows="1" placeholder="Ask IO anything" autocomplete="off"></textarea>
          <button type="button" class="askbar-act" data-go="library" aria-label="Files">${icon("folder", { size: 17 })}</button>
          <button type="button" class="askbar-act" data-go="conversation" aria-label="History">${icon("clockCounterClockwise", { size: 17 })}</button>
          <button type="submit" class="askbar-send" aria-label="Send">${icon("arrowUp", { size: 17 })}</button>
          <div class="askbar-live" aria-hidden="true">
            <span class="askbar-bars">${"<i></i>".repeat(6)}</span>
            <span class="askbar-live-label">Listening…</span>
            <span class="askbar-elapsed mono">0:00</span>
          </div>
        </form>
      </div>
    </section>`;

  const orb = Orb(root.querySelector(".standby-orb"), { mode: "standby", size: 250 });

  const hEl = root.querySelector(".clk-h");
  const mEl = root.querySelector(".clk-m");
  const dayEl = root.querySelector(".clk-day");
  const dateEl = root.querySelector(".clk-date");
  const tick = () => {
    const now = new Date();
    hEl.textContent = pad(now.getHours());
    mEl.textContent = pad(now.getMinutes());
    dayEl.textContent = weekday(now);
    dateEl.textContent = monthDay(now);
  };
  tick();
  const timer = setInterval(tick, 10000);

  const form = root.querySelector(".askbar");
  const input = root.querySelector(".askbar-in");
  const liveLabel = root.querySelector(".askbar-live-label");
  const elapsedEl = root.querySelector(".askbar-elapsed");

  const grow = () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 132) + "px";
  };
  input.addEventListener("input", grow);
  grow();

  const submit = (text) => {
    const v = (text ?? input.value).trim();
    if (!v) return;
    input.value = "";
    grow();
    freezePlaceholder();
    form.classList.add("busy");
    input.setAttribute("placeholder", "Working…");
    ctx._pending = v;            // conversation.js sends it once it's mounted
    ctx.goto("conversation");
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  root.querySelectorAll(".askbar-act").forEach((b) => {
    b.addEventListener("click", () => ctx.goto(b.dataset.go));
  });

  // ── rotating placeholder ──────────────────────────────────────────────
  const shuffled = EXAMPLES.slice().sort(() => Math.random() - 0.5);
  let exIdx = 0, exFrozen = false, phTimer = null, phSwap = null;
  const cyclePlaceholder = () => {
    if (exFrozen) return;
    input.classList.add("ph-fade");
    phSwap = setTimeout(() => {
      input.setAttribute("placeholder", shuffled[exIdx++ % shuffled.length]);
      input.classList.remove("ph-fade");
    }, 200);
  };
  const freezePlaceholder = () => {
    if (exFrozen) return;
    exFrozen = true;
    clearInterval(phTimer); clearTimeout(phSwap);
    input.classList.remove("ph-fade");
  };
  // keep cycling while the field is focused-but-empty; stop once they type
  input.addEventListener("input", () => { if (input.value) freezePlaceholder(); });
  const phFirst = setTimeout(cyclePlaceholder, 1600);
  phTimer = setInterval(cyclePlaceholder, 4500);

  // ── voice: record → live feedback (interim words on Soniox) → send ────
  let mic = null, recording = false, raf = null, recT0 = 0;
  const micBtn = root.querySelector(".askbar-mic");

  const liveTick = () => {
    if (!recording || !mic) return;
    orb.setLevel(0.2 + mic.level() * 0.8);
    elapsedEl.textContent = mmss(Math.floor((performance.now() - recT0) / 1000));
    raf = requestAnimationFrame(liveTick);
  };

  const resetVoice = () => {
    recording = false;
    if (raf) { cancelAnimationFrame(raf); raf = null; }
    form.classList.remove("recording", "transcribing");
    liveLabel.textContent = "Listening…";
    elapsedEl.textContent = "0:00";
    orb.setMode("standby");
    orb.setLevel(0.32);
  };

  const startVoice = async () => {
    if (!ctx.store.get().voiceOk) { ctx.openSettings(); return; }
    mic = createMic(ctx, {
      onText: (t) => { if (recording) liveLabel.textContent = t || "Listening…"; },
    });
    try {
      await mic.start();
    } catch { mic = null; return; }
    recording = true;
    form.classList.add("recording");
    orb.setMode("listening");
    recT0 = performance.now();
    raf = requestAnimationFrame(liveTick);
  };

  const stopVoice = async () => {
    if (!mic || !recording) return;
    const m = mic; mic = null; recording = false;
    if (raf) { cancelAnimationFrame(raf); raf = null; }
    form.classList.add("transcribing");
    if (!m.streaming) liveLabel.textContent = "Transcribing…";
    orb.setMode("thinking");
    let transcript = "";
    try { ({ transcript } = await m.stop()); } catch { /* ignore */ }
    resetVoice();
    if (transcript && transcript.trim()) submit(transcript);
  };

  micBtn.addEventListener("click", () => { recording ? stopVoice() : startVoice(); });

  // ── data ──────────────────────────────────────────────────────────────
  let data = { greeting_name: "there", stats: {}, chips: [] };
  ctx.api.standby().then((d) => {
    data = d;
    root.querySelector(".standby-greet").textContent =
      `${greet(data.stats && data.stats.clock)}, ${data.greeting_name}.`;
    const agenda = root.querySelector(".standby-agenda");
    const chips = data.chips || [];
    agenda.innerHTML = chips.map((c, i) =>
      `<button class="agenda-row${i === chips.length - 1 ? " dim" : ""}" type="button">
         <span class="agenda-when">${icon(
           c.icon === "list-checks" ? "listChecks" : c.icon === "users-three" ? "usersThree" : "circle",
           { size: 12 },
         )}</span>
         <span class="agenda-text">${c.text}</span>
       </button>`).join("");
    agenda.onclick = (e) => {
      const b = e.target.closest(".agenda-row");
      if (b) submit(b.querySelector(".agenda-text").textContent.trim());
    };
  }).catch(() => { /* offline */ });

  const onKey = (e) => {
    if (e.code === "Space" && e.altKey && ctx.store.get().voiceOk) {
      e.preventDefault();
      recording ? stopVoice() : startVoice();
    }
  };
  document.addEventListener("keydown", onKey);
  setTimeout(() => input.focus(), 30);

  root._cleanup = () => {
    clearInterval(timer);
    clearInterval(phTimer); clearTimeout(phSwap); clearTimeout(phFirst);
    document.removeEventListener("keydown", onKey);
    if (raf) cancelAnimationFrame(raf);
    if (mic) { try { mic.stop(); } catch { /* ignore */ } }
    orb.destroy();
  };
}
