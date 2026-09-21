// What Settings → Updates says, given GET /update. Pure so it can be tested.
export function updateMessage(u) {
  if (!u) return { text: "Update checks are unavailable.", canApply: false, blocked: "" };
  if (u.enabled === false) {
    return { text: "Update checks are off ([updates] enabled = false).", canApply: false, blocked: "" };
  }
  if (u.error) return { text: `Couldn't check: ${u.error}`, canApply: false, blocked: "" };
  if (!u.available) return { text: "IO is up to date.", canApply: false, blocked: "" };
  const n = u.behind;
  const text = `${n} new change${n === 1 ? "" : "s"} available.`;
  if (u.dirty) {
    return {
      text, canApply: false,
      blocked: "You have local changes to tracked files. Commit or discard them before updating.",
    };
  }
  return { text, canApply: true, blocked: "" };
}
