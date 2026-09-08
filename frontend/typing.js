// typewriter reveal — filled in Plan 6 Task 6
export function revealText(el, text, opts = {}) {
  const { onDone } = opts;
  el.textContent = text;
  if (onDone) onDone();
  return () => {};
}
