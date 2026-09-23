// Local real-time STT — streams 16 kHz PCM16 to IO's own /ws/transcribe.
// Fully on-device (faster-whisper on the service). Same interface as
// SonioxStream so mic.js can swap them freely.

import { downsample, pcm16 } from "./pcm.js";

export class LocalStream {
  async start({ onText } = {}) {
    this._onText = onText;
    this._final = "";
    this._level = 0;

    this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this._ctx = new (window.AudioContext || window.webkitAudioContext)();
    const inRate = this._ctx.sampleRate;
    this._src = this._ctx.createMediaStreamSource(this._stream);
    this._proc = this._ctx.createScriptProcessor(4096, 1, 1);

    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/transcribe`;
    this._ws = new WebSocket(url);
    this._ws.binaryType = "arraybuffer";
    await new Promise((res, rej) => {
      const to = setTimeout(() => rej(new Error("local stt: connect timeout")), 8000);
      this._ws.onopen = () => { clearTimeout(to); res(); };
      this._ws.onerror = () => { clearTimeout(to); rej(new Error("local stt: ws error")); };
    });

    this._ws.onmessage = (e) => {
      let m;
      try { m = JSON.parse(e.data); } catch { return; }
      if (m.type === "partial" && m.text) {
        this._final = m.text;
        this._onText && this._onText(m.text);
      } else if (m.type === "final") {
        if (m.text) this._final = m.text;
        this._closed && this._closed();
      } else if (m.type === "error") {
        this._err = m.message;
      }
    };
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

  async stop() {
    try { this._proc && this._proc.disconnect(); } catch { /* ignore */ }
    try { this._src && this._src.disconnect(); } catch { /* ignore */ }
    this._stream && this._stream.getTracks().forEach((t) => t.stop());
    try {
      if (this._ws && this._ws.readyState === 1) {
        this._ws.send(JSON.stringify({ type: "end" }));   // triggers the final pass
        await new Promise((res) => { this._closed = res; setTimeout(res, 5000); });
      }
    } catch { /* ignore */ }
    try { this._ws && this._ws.close(); } catch { /* ignore */ }
    try { this._ctx && this._ctx.close(); } catch { /* ignore */ }
    return (this._final || "").replace(/\s+/g, " ").trim();
  }
}
