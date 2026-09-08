import { renderMarkdown } from "../vendor/markdown.js";

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function renderMessage(role, text, shape) {
  const div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : "io");
  div.innerHTML = shape === "markdown"
    ? renderMarkdown(text)
    : esc(String(text)).replace(/\n/g, "<br>");
  return div;
}
