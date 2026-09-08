// The IO voice presence — layered rotating rings + breathing core.
// Modes: standby | listening | thinking | speaking. Reduced-motion safe.
// Mounts a fixed-size .orb element INSIDE the host so the host's layout
// (flex/grid sizing) never distorts the circle.

export function Orb(host, { mode = "standby", size = 300 } = {}) {
  const el = document.createElement("div");
  el.className = "orb";
  el.dataset.mode = mode;
  el.style.setProperty("--orb-size", size + "px");
  el.innerHTML = `
    <div class="orb-ticks"></div>
    <div class="orb-ring orb-ring-static"></div>
    <div class="orb-ring orb-ring-arc"></div>
    <div class="orb-ring orb-ring-dashed"></div>
    <div class="orb-halo"></div>
    <div class="orb-core"></div>
    <div class="orb-bars">${"<i></i>".repeat(12)}</div>
  `;
  host.appendChild(el);

  function setMode(m) { el.dataset.mode = m; }
  function setLevel(v) {
    el.style.setProperty("--orb-level", Math.max(0, Math.min(1, v)).toFixed(3));
  }
  setLevel(mode === "listening" ? 1 : 0.32);

  return { setMode, setLevel, el, destroy: () => el.remove() };
}
