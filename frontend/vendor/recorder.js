// Web Audio -> 16 kHz mono PCM16 WAV. `encodeWav` is pure (node-testable).

export function encodeWav(float32, inRate, outRate = 16000) {
  const down = downsample(float32, inRate, outRate);
  const buf = new ArrayBuffer(44 + down.length * 2);
  const view = new DataView(buf);
  const ws = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
  ws(0, "RIFF");
  view.setUint32(4, 36 + down.length * 2, true);
  ws(8, "WAVE");
  ws(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, outRate, true);
  view.setUint32(28, outRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ws(36, "data");
  view.setUint32(40, down.length * 2, true);
  let off = 44;
  for (let i = 0; i < down.length; i++, off += 2) {
    const s = Math.max(-1, Math.min(1, down[i]));
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

function downsample(data, inRate, outRate) {
  if (outRate >= inRate) return data;
  const ratio = inRate / outRate;
  const out = new Float32Array(Math.floor(data.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.floor((i + 1) * ratio);
    let sum = 0, n = 0;
    for (let j = start; j < end && j < data.length; j++) { sum += data[j]; n++; }
    out[i] = n ? sum / n : 0;
  }
  return out;
}

export class WavRecorder {
  async start() {
    this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this._ctx = new (window.AudioContext || window.webkitAudioContext)();
    this._src = this._ctx.createMediaStreamSource(this._stream);
    this._proc = this._ctx.createScriptProcessor(4096, 1, 1);
    this._chunks = [];
    this._level = 0;
    this._proc.onaudioprocess = (e) => {
      const ch = e.inputBuffer.getChannelData(0);
      this._chunks.push(new Float32Array(ch));
      let s = 0;
      for (let i = 0; i < ch.length; i++) s += ch[i] * ch[i];
      this._level = Math.min(1, Math.sqrt(s / ch.length) * 4);
    };
    this._src.connect(this._proc);
    this._proc.connect(this._ctx.destination);
  }

  level() { return this._level || 0; }

  async stop() {
    this._proc && this._proc.disconnect();
    this._src && this._src.disconnect();
    this._stream && this._stream.getTracks().forEach((t) => t.stop());
    const rate = this._ctx ? this._ctx.sampleRate : 48000;
    this._ctx && this._ctx.close();
    const total = this._chunks.reduce((n, c) => n + c.length, 0);
    const flat = new Float32Array(total);
    let o = 0;
    for (const c of this._chunks) { flat.set(c, o); o += c.length; }
    return new Blob([encodeWav(flat, rate)], { type: "audio/wav" });
  }

  dispose() { try { this.stop(); } catch { /* ignore */ } }
}
