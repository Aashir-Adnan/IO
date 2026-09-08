import { Orb } from "../components/orb.js";
import { Composer } from "../components/composer.js";
import { icon } from "../vendor/icons.js";
import { sendTurn } from "./conversation.js";

function greet(clockIso) {
  const h = clockIso ? new Date(clockIso).getHours() : new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export async function mount(root, ctx) {
  const status = document.getElementById("status");
  if (status) status.textContent = "LOCAL · ENCRYPTED";

  root.innerHTML = `
    <section class="standby">
      <div class="standby-head">
        <div>
          <div class="mono kicker">STANDBY</div>
          <h1 class="standby-greet"></h1>
        </div>
        <div class="statrow mono"></div>
      </div>
      <div class="standby-orb"></div>
      <div class="standby-dock">
        <div class="chips"></div>
        <div class="standby-composer"></div>
      </div>
    </section>`;

  const orb = Orb(root.querySelector(".standby-orb"), { mode: "standby", size: 320 });

  let data = { greeting_name: "there", stats: {}, chips: [] };
  try { data = await ctx.api.standby(); } catch { /* offline */ }

  root.querySelector(".standby-greet").textContent =
    `${greet(data.stats.clock)}, ${data.greeting_name}.`;

  const s = data.stats || {};
  const clock = s.clock ? new Date(s.clock) : new Date();
  root.querySelector(".statrow").innerHTML = [
    `<span><b>${s.memories ?? 0}</b> MEMORIES</span>`,
    `<span><b>${s.recall_ms ?? 0}</b> ms RECALL</span>`,
    `<span><b>${clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</b></span>`,
  ].join("<span class='sep'>·</span>");

  const chips = root.querySelector(".chips");
  chips.innerHTML = (data.chips || []).map((c) =>
    `<button class="chip" type="button">${icon(c.icon === "list-checks" ? "listChecks" : c.icon === "users-three" ? "usersThree" : "circle", { size: 12 })}<span>${c.text}</span></button>`
  ).join("");
  chips.addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    ctx.goto("conversation");
    sendTurn(ctx, b.textContent.trim());
  });

  Composer(root.querySelector(".standby-composer"), {
    onSend: (text) => { ctx.goto("conversation"); sendTurn(ctx, text); },
    onMic: () => ctx.store.get().voiceOk ? ctx.goto("talk") : null,
  }).focus();

  const onKey = (e) => {
    if (e.code === "Space" && e.altKey && ctx.store.get().voiceOk) {
      e.preventDefault(); ctx.goto("talk");
    }
  };
  document.addEventListener("keydown", onKey);
  root._cleanup = () => document.removeEventListener("keydown", onKey);
}
