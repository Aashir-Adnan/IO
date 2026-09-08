import { icon } from "../vendor/icons.js";

export function Composer(root, { onSend, onMic, compact = false, placeholder } = {}) {
  const el = document.createElement("div");
  el.className = "composer" + (compact ? " compact" : "");
  el.innerHTML = `
    ${compact ? "" : '<span class="composer-lbl mono">INPUT</span>'}
    <button class="composer-mic" type="button" aria-label="Voice">${icon("mic", { size: 16 })}</button>
    <textarea rows="1" placeholder="${placeholder || "Ask IO, or hold ⌥ Space to talk"}"></textarea>
    ${compact ? `<button class="composer-send" type="button" aria-label="Send">${icon("arrowUp", { size: 16 })}</button>` : ""}
  `;
  root.appendChild(el);

  const ta = el.querySelector("textarea");
  const grow = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 120) + "px"; };
  ta.addEventListener("input", grow);
  grow();

  const send = () => {
    const v = ta.value.trim();
    if (!v) return;
    ta.value = ""; grow();
    onSend && onSend(v);
  };
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  el.querySelector(".composer-mic").addEventListener("click", () => onMic && onMic());
  const sendBtn = el.querySelector(".composer-send");
  if (sendBtn) sendBtn.addEventListener("click", send);

  return {
    setBusy: (b) => { ta.disabled = b; el.classList.toggle("busy", b); },
    focus: () => ta.focus(),
    clear: () => { ta.value = ""; grow(); },
  };
}
