// Soniox real-time STT — streams 16 kHz PCM16 mic audio straight to
// stt-rt.soniox.com and emits interim + final transcripts. The temp token
// comes from IO's /voice/stream-token so the real key never reaches the
// browser. Local-first: this path is gated on [voice] stt_provider="soniox"
// + SONIOX_API_KEY (see rules/local-first.md); with no key IO reports
// streaming:false and the mic uses local Whisper instead.

import { downsample, pcm16 } from "./pcm.js";

export class SonioxStream {
  // token: { api_key, model, websocket_url }
  async start({ token, onText } = {}) {
    this._onText = onText;
    this._final = "";
    this._level = 0;
    this._err = null;

    this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this._ctx = new (window.AudioContext || window.webkitAudioContext)();
    const inRate = this._ctx.sampleRate;
    this._src = this._ctx.createMediaStreamSource(this._stream);
    this._proc = this._ctx.createScriptProcessor(4096, 1, 1);

    this._ws = new WebSocket(token.websocket_url);
    this._ws.binaryType = "arraybuffer";
    await new Promise((res, rej) => {
      const to = setTimeout(() => rej(new Error("soniox: connect timeout")), 8000);
      this._ws.onopen = () => {
        clearTimeout(to);
        this._ws.send(JSON.stringify({
          api_key: token.api_key,
          model: token.model,
          audio_format: "pcm_s16le",
          sample_rate: 16000,
          num_channels: 1,
          language_hints: ["en"],
          enable_endpoint_detection: true,
        }));
        res();
      };
      this._ws.onerror = () => { clearTimeout(to); rej(new Error("soniox: ws error")); };
    });

    this._ws.onmessage = (e) => this._onMessage(e);
    this._ws.onclose = () => { this._closed && this._closed(); };

    this._proc.onaudioprocess = (ev) => {
      const ch = ev.inputBuffer.getChannelData(0);
      let s = 0;
      for (let i = 0; i < ch.length; i++) s += ch[i] * ch[i];
      this._level = Math.min(1, Math.sqrt(s / ch.length) * 4);
      if (this._ws && this._ws.readyState === 1) {
        this._ws.send(pcm16(downsample(ch, inRate, 16000)));
      }
    };
    this._src.connect(this._proc);
    this._proc.connect(this._ctx.destination);
  }

  level() { return this._level || 0; }

  _onMessage(e) {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.error_code) { this._err = msg.error_message || String(msg.error_code); return; }
    let interim = "";
    for (const t of msg.tokens || []) {
      if (t.is_final) this._final += t.text;
      else interim += t.text;
    }
    this._onText && this._onText((this._final + interim).replace(/\s+/g, " ").trim());
  }

  async stop() {
    try { this._proc && this._proc.disconnect(); } catch { /* ignore */ }
    try { this._src && this._src.disconnect(); } catch { /* ignore */ }
    this._stream && this._stream.getTracks().forEach((t) => t.stop());

    try {
      if (this._ws && this._ws.readyState === 1) {
        this._ws.send("");                       // end-of-audio
        await new Promise((res) => { this._closed = res; setTimeout(res, 1600); });
      }
    } catch { /* ignore */ }
    try { this._ws && this._ws.close(); } catch { /* ignore */ }
    try { this._ctx && this._ctx.close(); } catch { /* ignore */ }

    return (this._final || "").replace(/\s+/g, " ").trim();
  }
}
