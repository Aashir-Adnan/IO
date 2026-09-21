import { icon } from "../vendor/icons.js";
import { esc } from "./util.js";
import { isValidZone, zoneInfo } from "./tz.js";

const local = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const defaults = () => [...new Set([local(), "UTC", "America/New_York", "Europe/London"])];

// World clocks: local time, weekday and UTC offset for a list of IANA zones.
// Computed in the browser; no network.
export function mountTimezones(el, ctx, { size = "S", settings }) {
  const zones = () => (settings.get().zones && settings.get().zones.length ? settings.get().zones : defaults());
  const listId = "tz-list-" + Math.random().toString(36).slice(2, 7);
  el.innerHTML = `<div class="tz size-${size}"><div class="tz-rows"></div>
    <form class="tz-add"><input class="w-input" list="${listId}" placeholder="Add a city, e.g. Asia/Tokyo" autocomplete="off" />
    <datalist id="${listId}"></datalist></form></div>`;
  const rows = el.querySelector(".tz-rows"), form = el.querySelector(".tz-add");
  const input = form.querySelector("input");
  try {
    form.querySelector("datalist").innerHTML =
      Intl.supportedValuesOf("timeZone").map((z) => `<option value="${esc(z)}"></option>`).join("");
  } catch { /* older engine: free text only */ }

  const paint = () => {
    const now = new Date();
    rows.innerHTML = zones().map((z) => {
      const i = zoneInfo(z, now);
      return `<div class="tz-row" data-zone="${esc(z)}">
        <span class="tz-city">${esc(i.city)}<small>${esc(i.day)} · ${esc(i.offset)}</small></span>
        <span class="tz-time">${esc(i.time)}</span>
        <button class="tz-x" type="button" aria-label="Remove ${esc(i.city)}">${icon("x", { size: 12 })}</button>
      </div>`;
    }).join("");
  };
  rows.addEventListener("click", (e) => {
    const b = e.target.closest(".tz-x");
    if (!b) return;
    const z = b.closest(".tz-row").dataset.zone;
    settings.set({ ...settings.get(), zones: zones().filter((x) => x !== z) });
    paint();
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const z = input.value.trim().replace(/ /g, "_");
    if (!isValidZone(z) || zones().includes(z)) { input.classList.add("bad"); return; }
    input.classList.remove("bad");
    settings.set({ ...settings.get(), zones: [...zones(), z] });
    input.value = "";
    paint();
  });
  paint();
  const timer = setInterval(paint, 15000);
  return () => clearInterval(timer);
}
