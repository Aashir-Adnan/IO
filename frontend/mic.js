// One mic abstraction over both STT modes. `createMic` picks Soniox real-time
// streaming when the service reports it (ctx.store.sttStreaming), else falls
// back to local Whisper batch (record → POST /voice/transcribe on stop).
//
//   const mic = createMic(ctx, { onText });   // onText: live interim string
//   await mic.start();                         // throws only on hard failure
//   mic.level();                               // 0..1 for the meter
//   const { transcript } = await mic.stop();

import { WavRecorder } from "./vendor/recorder.js";
import { SonioxStream } from "./vendor/soniox.js";
import { LocalStream } from "./vendor/localstream.js";

export function createMic(ctx, { onText } = {}) {
  let impl = null;
  let mode = null;   // "whisper-stream" | "soniox" | "batch"

  async function start() {
    const s = ctx.store.get();
    if (s.sttStreaming && s.sttProvider === "whisper-stream") {
      try {
        const ls = new LocalStream();
        await ls.start({ onText });
        impl = ls; mode = "whisper-stream";
        return;
      } catch { impl = null; }
    } else if (s.sttStreaming && s.sttProvider === "soniox") {
      try {
        const token = await ctx.api.sttStreamToken();
        const sx = new SonioxStream();
        await sx.start({ token, onText });
        impl = sx; mode = "soniox";
        return;
      } catch { impl = null; }
    }
    const r = new WavRecorder();
    await r.start();
    impl = r; mode = "batch";
  }

  async function stop() {
    if (!impl) return { transcript: "" };
    const cur = impl; impl = null;
    if (mode === "soniox") {
      const text = await cur.stop();
      return { transcript: text };
    }
    const blob = await cur.stop();
    try { return await ctx.api.transcribeAudio(blob); }
    catch { return { transcript: "" }; }
  }

  return {
    start, stop,
    level: () => (impl && impl.level ? impl.level() : 0),
    get mode() { return mode; },
    get streaming() { return mode === "soniox" || mode === "whisper-stream"; },
  };
}
