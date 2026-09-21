import { esc, debounce } from "./util.js";

const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString([], { weekday: "short" });

// Weather for one chosen city (Open-Meteo, fetched by the service). The place
// lives in this widget's settings; until one is chosen it shows a city search.
export function mountWeather(el, ctx, { size = "S", settings }) {
  let alive = true, timer = null;
  el.innerHTML = `<div class="weather size-${size}"></div>`;
  const root = el.firstElementChild;

  const search = () => {
    root.innerHTML = `
      <input class="w-input" type="text" placeholder="Search for a city" autocomplete="off" />
      <div class="w-results"></div>`;
    const input = root.querySelector(".w-input"), out = root.querySelector(".w-results");
    const run = debounce(async () => {
      const q = input.value.trim();
      if (!q) { out.innerHTML = ""; return; }
      try {
        const res = await ctx.api.weatherSearch(q);
        if (!alive) return;
        out.innerHTML = res.length
          ? res.map((r, i) => `<button type="button" class="w-result" data-i="${i}">${esc(r.label)}</button>`).join("")
          : `<p class="w-note">No matches.</p>`;
        out.onclick = (e) => {
          const b = e.target.closest(".w-result");
          if (!b) return;
          const r = res[+b.dataset.i];
          settings.set({ place: { label: r.label, name: r.name, lat: r.lat, lon: r.lon } });
          start();
        };
      } catch (e) { out.innerHTML = `<p class="w-note">${esc(e.detail || "Search failed.")}</p>`; }
    }, 350);
    input.addEventListener("input", run);
    setTimeout(() => input.focus(), 30);
  };

  const show = async (place) => {
    try {
      const w = await ctx.api.weather(place.lat, place.lon);
      if (!alive) return;
      const days = size === "S" ? "" : `<div class="wx-days">${w.daily.map((d) =>
        `<div class="wx-day"><span>${esc(day(d.date))}</span><span>${esc(d.label)}</span>
         <b>${d.hi_c}°</b><span>${d.lo_c}°</span></div>`).join("")}</div>`;
      root.innerHTML = `
        <div class="wx-now">
          <div class="wx-temp">${w.temp_c}°</div>
          <div class="wx-meta"><b>${esc(w.label)}</b><span>Feels ${w.feels_c}° · H ${w.hi_c}° L ${w.lo_c}°</span></div>
        </div>
        <div class="wx-place"><span>${esc(place.name || place.label)}</span>
          <button class="w-link" type="button" data-act="change">Change</button></div>
        ${days}`;
      root.querySelector('[data-act="change"]').onclick = () => { settings.set({}); start(); };
    } catch (e) {
      if (!alive) return;
      root.innerHTML = `<p class="w-note">${esc(e.detail || "Couldn't load the weather.")}</p>
        <button class="w-link" type="button" data-act="retry">Try again</button>`;
      root.querySelector('[data-act="retry"]').onclick = () => show(place);
    }
  };

  function start() {
    clearInterval(timer);
    const { place } = settings.get();
    if (!place) return search();
    show(place);
    timer = setInterval(() => show(place), 15 * 60 * 1000);
  }
  start();
  return () => { alive = false; clearInterval(timer); };
}
