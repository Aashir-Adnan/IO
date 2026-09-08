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

  const step = () => {
    if (cancelled) return;
    const elapsed = clock() - start;
    if (elapsed < minThinkMs) {
      requestAnimationFrame(step);
      return;
    }
    const rate = total.length > 240 ? cps * 2.4 : cps;
    const target = Math.min(total.length, Math.floor(((elapsed - minThinkMs) / 1000) * rate));
    if (target > shown) {
      shown = target;
      el.textContent = total.slice(0, shown);
      onProgress && onProgress(el.textContent);
    }
    if (shown >= total.length) { onDone && onDone(); return; }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);

  return function cancel() {
    cancelled = true;
    el.textContent = total;
    onProgress && onProgress(total);
    onDone && onDone();
  };
}
