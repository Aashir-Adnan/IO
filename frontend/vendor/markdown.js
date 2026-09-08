// Minimal Markdown -> HTML, dependency-free (upgraded in Plan 6 Task 6).
function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
export function renderMarkdown(src) {
  return String(src).split(/\n{2,}/).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
}
