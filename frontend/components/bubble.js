export function userBubble(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  return el;
}

export function ioBubble() {
  const el = document.createElement("div");
  el.className = "msg io";
  el.innerHTML = `
    <span class="io-avatar"></span>
    <div class="io-wrap">
      <div class="io-body"></div>
      <div class="io-cards"></div>
      <div class="io-actions"></div>
    </div>`;
  const body = el.querySelector(".io-body");
  return {
    el,
    body,
    cards: el.querySelector(".io-cards"),
    actions: el.querySelector(".io-actions"),
    setStreaming: (on) => el.classList.toggle("streaming", on),
  };
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}
