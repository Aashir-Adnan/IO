// "Thought for 4.2s" — the collapsed summary once a turn's steps are done.
export function thoughtLabel(secs) {
  if (secs < 0.1) return "Thought for a moment";
  if (secs < 10) return `Thought for ${secs.toFixed(1)}s`;
  const s = Math.round(secs);
  if (s < 60) return `Thought for ${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  return `Thought for ${m}m${r ? ` ${r}s` : ""}`;
}
