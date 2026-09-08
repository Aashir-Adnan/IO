import { renderMessage } from "../components/message.js";

export function mount(root, store, send) {
  root.innerHTML = "";
  const log = document.createElement("div");
  log.id = "log";
  const form = document.createElement("form");
  form.className = "chat-input";
  form.innerHTML =
    `<input id="q" autocomplete="off" placeholder="Tell io something, or ask a question&hellip;" />` +
    `<button type="submit">Send</button>`;
  root.append(log, form);

  const draw = () => {
    log.innerHTML = "";
    for (const m of store.transcript) log.append(renderMessage(m.role, m.text, m.shape));
    log.scrollTop = log.scrollHeight;
  };
  draw();
  store._onChange = draw;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = form.querySelector("#q");
    const text = q.value.trim();
    if (!text) return;
    q.value = "";
    send(text);
  });
}
