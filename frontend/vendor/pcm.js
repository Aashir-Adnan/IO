// Shared PCM helpers for the streaming STT paths (soniox.js, localstream.js).

export function downsample(data, inRate, outRate) {
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

export function pcm16(float32) {
  const buf = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}
