// What Settings → Account says, given GET /sync. Pure so it can be tested.
function ago(secs) {
  if (secs < 30) return "just now";
  const m = Math.floor(secs / 60);
  if (m < 60) return `${Math.max(1, m)} min ago`;
  const h = Math.floor(secs / 3600);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(secs / 86400)} d ago`;
}

const NONE = { canSignIn: false, canSync: false, canSignOut: false, busy: false };

export function syncMessage(s, now = Date.now() / 1000) {
  if (!s) return { ...NONE, text: "Sync is unavailable.", state: "off", where: "" };
  if (!s.enabled) {
    return { ...NONE, state: "off", where: "",
      text: "Sync is off. Turn it on in config.local.toml ([sync] enabled = true)." };
  }
  const folder = s.mode === "folder";
  const where = folder ? "Through a shared folder" : "Through your Google Drive";
  const auth = { canSignIn: false, canSync: true, canSignOut: !folder };
  if (s.signing_in) {
    return { ...NONE, busy: true, state: "busy", where,
      text: "Waiting for Google sign-in in your browser…" };
  }
  if (!s.signed_in) {
    return { ...NONE, canSignIn: true, state: "off", where, text: "Not signed in." };
  }
  if (s.syncing) return { ...auth, busy: true, state: "busy", where, text: "Syncing…" };
  if (s.error) {
    return { ...auth, busy: false, state: "error", where, text: `Sync problem: ${s.error}` };
  }
  const text = s.last_synced_at
    ? `Synced ${ago(now - s.last_synced_at)}`
    : "Signed in. Not synced yet.";
  return { ...auth, busy: false, state: s.last_synced_at ? "ok" : "off", where, text };
}
