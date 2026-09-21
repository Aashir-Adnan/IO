import { icon } from "../vendor/icons.js";
import { esc } from "./util.js";

const ICON = { overdue: "listChecks", today: "listChecks", occasion: "usersThree" };

// "Important": IO's own alerts (overdue / today / upcoming occasions) followed
// by unread important Gmail (sender + subject). Gmail is opt-in: until the user
// connects it the widget shows a Connect button and nothing else about mail.
export function mountAlerts(el, ctx, { size = "M" }) {
  let alive = true, poll = null;
  el.innerHTML = `<div class="alerts size-${size}"><div class="al-own"></div><div class="al-mail"></div></div>`;
  const own = el.querySelector(".al-own"), mail = el.querySelector(".al-mail");

  const paintOwn = (items) => {
    own.innerHTML = items.length
      ? items.map((a) => `<div class="al-row ${a.kind === "overdue" ? "bad" : ""}">
          <span class="al-ic">${icon(ICON[a.kind] || "circle", { size: 15 })}</span>
          <span class="al-text">${esc(a.text)}${a.detail ? `<small>${esc(a.detail)}</small>` : ""}</span></div>`).join("")
      : `<div class="al-row quiet"><span class="al-ic">${icon("checkCircle", { size: 15 })}</span><span class="al-text">All quiet</span></div>`;
  };

  const paintMail = (g) => {
    if (!g.connected) {
      mail.innerHTML = `<button class="w-link" type="button" data-act="connect">Connect Gmail</button>
        <small class="w-note">Shows unread important mail: sender and subject only.</small>`;
      mail.querySelector('[data-act="connect"]').onclick = async () => {
        await ctx.api.gmailConnect().catch(() => {});
        const t = setInterval(async () => {
          if (!alive) return clearInterval(t);
          const s = await ctx.api.gmail().catch(() => null);
          if (s && !s.connecting) { clearInterval(t); loadMail(); }
        }, 1500);
      };
      return;
    }
    if (g.error) { mail.innerHTML = `<p class="w-note">Mail: ${esc(g.error)}</p>`; return; }
    mail.innerHTML = g.items.length
      ? `<div class="al-h">Mail</div>` + g.items.map((m) => `<div class="al-row mail">
          <span class="al-ic">${icon("chatDots", { size: 15 })}</span>
          <span class="al-text">${esc(m.subject)}<small>${esc(m.from)}</small></span></div>`).join("")
      : `<div class="al-h">Mail</div><div class="al-row quiet"><span class="al-text">No unread important mail</span></div>`;
  };

  const loadOwn = () => ctx.api.alerts().then((a) => alive && paintOwn(a)).catch(() => alive && (own.innerHTML = `<p class="w-note">Couldn't load alerts.</p>`));
  const loadMail = () => ctx.api.gmailImportant().then((g) => alive && paintMail(g)).catch(() => {});
  loadOwn(); loadMail();
  poll = setInterval(() => { loadOwn(); loadMail(); }, 60000);
  return () => { alive = false; clearInterval(poll); };
}
