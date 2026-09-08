function initials(name) {
  return (name || "?").split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase();
}
function escape(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function mountInspector(root, panel) {
  if (!panel) return clearInspector(root);
  const pct = Math.round((panel.confidence || 0) * 100);
  root.classList.add("open");
  root.innerHTML = `
    <div class="mono kicker">MEMORY INSPECTOR</div>
    <div class="insp-head">
      <span class="insp-avatar">${initials(panel.name)}</span>
      <div>
        <div class="insp-name">${escape(panel.name)}</div>
        <div class="mono insp-sub">${escape(panel.subtitle)}</div>
      </div>
    </div>
    <div class="hair"></div>
    <div class="insp-facts">
      ${(panel.facts || []).map((f) => `
        <div class="insp-fact">
          <div class="mono kicker">${escape(f.label)}</div>
          <div class="insp-fact-t">${escape(f.text)}</div>
        </div>`).join("")}
    </div>
    <span class="grow"></span>
    <div class="mono kicker">CONFIDENCE</div>
    <div class="insp-bar"><span style="width:${pct}%"></span></div>
    <div class="mono insp-conf">${pct}% · SOURCED FROM ${panel.sourced_from} NOTES</div>
    <button class="btn btn-primary insp-open" title="coming soon">Open ${escape(panel.name)}'s file</button>`;
}

export function clearInspector(root) {
  root.classList.remove("open");
  root.innerHTML = "";
}
