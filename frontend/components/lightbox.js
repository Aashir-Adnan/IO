// Full-screen viewer. Open with:
//   Lightbox({ raw_url, kind })   — image / video
//   Lightbox({ text, name })      — a text file (md, js, ts, txt, …)
// Click the backdrop / the close button / Esc to dismiss.
import { icon } from "../vendor/icons.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

let el = null;
let onKey = null;

export function Lightbox(opts) {
  close();
  el = document.createElement("div");
  el.className = "lightbox" + (opts.text != null ? " lightbox-text" : "");

  let stage;
  if (opts.text != null) {
    stage = `<div class="lightbox-doc">
      <div class="lightbox-doc-head">${esc(opts.name || "file")}</div>
      <pre class="lightbox-doc-body">${esc(opts.text)}</pre>
    </div>`;
  } else if (opts.kind === "video") {
    stage = `<div class="lightbox-stage"><video src="${opts.raw_url}" controls autoplay playsinline></video></div>`;
  } else {
    stage = `<div class="lightbox-stage"><img src="${opts.raw_url}" alt=""></div>`;
  }

  el.innerHTML = `<button class="lightbox-close" aria-label="Close">${icon("x", { size: 20 })}</button>${stage}`;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("in"));

  el.addEventListener("click", (e) => {
    if (e.target === el || e.target.closest(".lightbox-close")) close();
  });
  onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
}

export function close() {
  if (onKey) { document.removeEventListener("keydown", onKey, true); onKey = null; }
  if (el) {
    const gone = el; el = null;
    gone.classList.remove("in");
    setTimeout(() => gone.remove(), 220);
  }
}

export function isOpen() { return el !== null; }
