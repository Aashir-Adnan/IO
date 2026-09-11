// Thin client for the IO service. All calls are relative -> same origin (127.0.0.1).
export function Api(base = "") {
  const b = base.replace(/\/$/, "");
  const j = async (r) => {
    if (r.ok) return r.json();
    let detail = "";
    try { detail = (await r.json()).detail; } catch { /* no body */ }
    const err = new Error(detail ? `${r.status} ${detail}` : `${r.status} ${r.statusText}`);
    err.status = r.status;
    err.detail = typeof detail === "string" ? detail : "";
    throw err;
  };

  return {
    async health() { return j(await fetch(`${b}/health`)); },
    async voiceHealth() {
      try { return j(await fetch(`${b}/voice/health`)); }
      catch (e) { return { whisper: false, piper: false, voice: "?", reason: String(e) }; }
    },
    async standby() { return j(await fetch(`${b}/standby`)); },
    async sendText({ text, conversationId, confirmToken }) {
      return j(await fetch(`${b}/utterance`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          text, source: "text",
          conversation_id: conversationId ?? null,
          confirm_token: confirmToken ?? null,
        }),
      }));
    },
    async sendVoice(wavBlob, { conversationId, speak = true } = {}) {
      const fd = new FormData();
      fd.append("audio", wavBlob, "turn.wav");
      fd.append("speak", speak ? "1" : "0");
      if (conversationId) fd.append("conversation_id", String(conversationId));
      return j(await fetch(`${b}/voice`, { method: "POST", body: fd }));
    },
    async conversation(id, before) {
      const q = new URLSearchParams();
      if (id) q.set("id", id);
      if (before) q.set("before", before);
      return j(await fetch(`${b}/conversation?${q}`));
    },
    async conversations() { return j(await fetch(`${b}/conversations`)); },
    async newConversation() { return j(await fetch(`${b}/conversation`, { method: "POST" })); },
    async entity(etype, id) { return j(await fetch(`${b}/entity/${etype}/${id}`)); },
    async deleteEntity(etype, id) {
      return j(await fetch(`${b}/entity/${etype}/${id}`, { method: "DELETE" }));
    },
    async records({ limit = 300, kind, domain } = {}) {
      const q = new URLSearchParams({ limit });
      if (kind) q.set("kind", kind);
      if (domain) q.set("domain", domain);
      return j(await fetch(`${b}/records?${q}`));
    },
    async collections() { return j(await fetch(`${b}/collections`)); },
    async editRecord(id, patch) {
      return j(await fetch(`${b}/record/${id}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify(patch),
      }));
    },
    async deleteRecord(id) {
      return j(await fetch(`${b}/record/${id}`, { method: "DELETE" }));
    },

    async files() { return j(await fetch(`${b}/files`)); },
    async registerFile(path) {
      return j(await fetch(`${b}/files`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path }),
      }));
    },
    async forgetFile(path) {
      return j(await fetch(`${b}/files`, {
        method: "DELETE", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path }),
      }));
    },
    async reindexFiles(path) {
      return j(await fetch(`${b}/files/reindex`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: path || null }),
      }));
    },
    async filesStatus() { return j(await fetch(`${b}/files/status`)); },
    async fileContent(path) {
      return j(await fetch(`${b}/files/content?path=` + encodeURIComponent(path)));
    },
    async openFolder({ path, phrase } = {}) {
      return j(await fetch(`${b}/files/open`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: path || null, phrase: phrase || null }),
      }));
    },
    async caption(path, text, source = "text") {
      return j(await fetch(`${b}/files/caption`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path, text, source }),
      }));
    },
    async captionConfirm(pending_token) {
      return j(await fetch(`${b}/files/caption/confirm`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ pending_token }),
      }));
    },
    async transcribeAudio(wavBlob) {
      const fd = new FormData();
      fd.append("audio", wavBlob, "speech.wav");
      return j(await fetch(`${b}/voice/transcribe`, { method: "POST", body: fd }));
    },
    async sttMode() {
      try { return j(await fetch(`${b}/voice/stt`)); }
      catch { return { provider: "whisper", streaming: false }; }
    },
    async sttStreamToken() {
      return j(await fetch(`${b}/voice/stream-token`, { method: "POST" }));
    },

    connectWs(onFrame) {
      let ws, closed = false, backoff = 500;
      const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
      const open = () => {
        ws = new WebSocket(url);
        ws.onopen = () => { backoff = 500; onFrame({ type: "_open" }); };
        ws.onmessage = (e) => onFrame(JSON.parse(e.data));
        ws.onclose = () => {
          onFrame({ type: "_close" });
          if (!closed) setTimeout(open, backoff = Math.min(backoff * 2, 8000));
        };
        ws.onerror = () => onFrame({ type: "_error" });
      };
      open();
      return {
        send: (obj) => { if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; } return false; },
        close: () => { closed = true; ws && ws.close(); },
      };
    },
  };
}
