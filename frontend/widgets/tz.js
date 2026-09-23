// Time-zone helpers for the Time zones widget. Pure Intl, no network.
export function isValidZone(zone) {
  if (!zone) return false;
  try { new Intl.DateTimeFormat("en", { timeZone: zone }); return true; }
  catch { return false; }
}

export const cityOf = (zone) => (zone.split("/").pop() || zone).replace(/_/g, " ");

// "GMT+05:30" -> "UTC+5:30", "GMT-04:00" -> "UTC-4", "GMT" -> "UTC"
function offsetLabel(zone, now) {
  const part = new Intl.DateTimeFormat("en", { timeZone: zone, timeZoneName: "longOffset" })
    .formatToParts(now).find((p) => p.type === "timeZoneName");
  const m = part && part.value.match(/GMT([+-])(\d{1,2})(?::(\d{2}))?/);
  if (!m) return "UTC";
  const h = parseInt(m[2], 10), min = m[3] && m[3] !== "00" ? m[3] : "";
  return h === 0 && !min ? "UTC" : `UTC${m[1]}${h}${min ? ":" + min : ""}`;
}

export function zoneInfo(zone, now = new Date()) {
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(now);
  const day = new Intl.DateTimeFormat("en", { timeZone: zone, weekday: "short" }).format(now);
  return { zone, city: cityOf(zone), time, day, offset: offsetLabel(zone, now) };
}
