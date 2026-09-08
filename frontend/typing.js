// Typewriter reveal with a deliberate "thinking" hold before the first char.
// `clock` is injectable for tests.
export function revealText(el, text, opts = {}) {
  const {
    cps = 45,
    minThinkMs = 600,
    onProgress,
    onDone,
    clock = () => performance.now(),
  } = opts;

  let cancelled = false;
  const start = clock();
  const total = String(text);
  let shown = 0;

  // setTimeout, not requestAnimationFrame: rAF is fully paused when the window
  // is hidden / minimised, which would freeze the transcript mid-reveal.
  const tick = (fn) => setTimeout(fn, 33);

  const finish = () => {
    if (shown < total.length) {
      el.textContent = total;
      onProgress && onProgress(total);
    }
    onDone && onDone();
  };

  const step = () => {
    if (cancelled) return;
    if (document.visibilityState === "hidden") { finish(); return; }
    const elapsed = clock() - start;
    if (elapsed < minThinkMs) { tick(step); return; }
    const rate = total.length > 240 ? cps * 2.4 : cps;
    const target = Math.min(total.length, Math.floor(((elapsed - minThinkMs) / 1000) * rate));
    if (target > shown) {
      shown = target;
      el.textContent = total.slice(0, shown);
      onProgress && onProgress(el.textContent);
    }
    if (shown >= total.length) { onDone && onDone(); return; }
    tick(step);
  };
  tick(step);

  return function cancel() {
    cancelled = true;
    el.textContent = total;
    onProgress && onProgress(total);
    onDone && onDone();
  };
}
