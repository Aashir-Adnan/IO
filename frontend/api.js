// Thin client for the IO service. All calls are relative -> same origin (127.0.0.1).
export function Api(base = "") {
  const b = base.replace(/\/$/, "");
  const j = (r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.json(); };

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
