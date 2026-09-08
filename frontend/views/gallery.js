import { icon } from "../vendor/icons.js";
import { Composer } from "../components/composer.js";
import { WavRecorder } from "../vendor/recorder.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function mount(root, ctx) {
  const g = ctx.store.get().gallery;
  if (!g) { root.innerHTML = `<p class="gallery-empty">Nothing open.</p>`; return; }

  root.innerHTML = `
    <section class="gallery">
      <header class="gallery-head">
        <button class="gallery-back">${icon("folder", { size: 14 })} Files</button>
        <h1>${esc(g.folder_path.split(/[\\/]/).pop())}</h1>
        <span class="mono">${g.count} item${g.count === 1 ? "" : "s"}</span>
      </header>
      <div class="gallery-grid"></div>
      <aside class="gallery-detail" hidden></aside>
    </section>`;

  root.querySelector(".gallery-back").onclick = () => ctx.goto("files");
  const grid = root.querySelector(".gallery-grid");
  const detail = root.querySelector(".gallery-detail");

  for (const it of g.items) {
    const tile = document.createElement("button");
    tile.className = "tile";
    tile.innerHTML = it.thumb_url
      ? `<img loading="lazy" src="${it.thumb_url}" alt="">`
      : `<span class="tile-glyph">${icon(it.media_kind === "video" ? "filmSlate" : "image", { size: 28 })}</span>`;
    if (it.media_kind === "video") {
      const p = document.createElement("span");
      p.className = "tile-play";
      p.innerHTML = icon("play", { size: 20 });
      tile.appendChild(p);
    }
    tile.onclick = () => showDetail(it);
    grid.appendChild(tile);
  }

  function showDetail(it) {
    detail.hidden = false;
    detail.innerHTML = `
      <button class="detail-close">${icon("check", { size: 14 })}</button>
      <div class="detail-media">${
        it.media_kind === "video"
          ? `<video controls preload="metadata" src="${it.raw_url}"></video>`
          : `<img src="${it.raw_url}" alt="">`
      }</div>
      <div class="detail-caption">
        <div class="detail-cap-text">${it.caption ? esc(it.caption) : ""}</div>
        <div class="detail-chips"></div>
        <div class="detail-compose"></div>
        <div class="detail-gate" hidden></div>
      </div>`;
    detail.querySelector(".detail-close").onclick = () => { detail.hidden = true; };
    renderChips(it);

    Composer(detail.querySelector(".detail-compose"), {
      compact: true,
      placeholder: it.media_kind === "video"
        ? "Tell me about this video" : "Tell me about this picture",
      onSend: (text) => submitCaption(it, text),
      onMic: () => micCaption(it),
    });

    function renderChips(item) {
      detail.querySelector(".detail-chips").innerHTML =
        (item.entities || []).map((e) =>
          `<button class="chip${e.etype === "person" ? " person" : ""}" data-etype="${e.etype}" data-id="${e.id}">${esc(e.name)}</button>`).join("");
      detail.querySelectorAll(".detail-chips .chip").forEach((c) => {
        c.onclick = () => ctx.openInspector && ctx.openInspector(c.dataset.etype, +c.dataset.id);
      });
    }

    async function submitCaption(item, text) {
      try {
        const res = await ctx.api.caption(item.path, text, "text");
        if (res.gated) return showGate(item, res.pending_token, res.reasons);
        applyCaptionResult(item, res);
      } catch { /* ignore */ }
    }

    function applyCaptionResult(item, res) {
      item.caption = res.caption;
      item.entities = res.entities;
      detail.querySelector(".detail-cap-text").textContent = res.caption;
      renderChips(item);
    }

    function showGate(item, token, reasons) {
      const gate = detail.querySelector(".detail-gate");
      gate.hidden = false;
      gate.innerHTML =
        `<p>${esc((reasons || []).join(" "))}</p>` +
        `<button class="btn btn-primary" data-yes>Yes</button>` +
        `<button class="btn" data-no>Edit</button>`;
      gate.querySelector("[data-yes]").onclick = async () => {
        gate.hidden = true;
        try {
          applyCaptionResult(item, await ctx.api.captionConfirm(token));
        } catch { /* ignore */ }
      };
      gate.querySelector("[data-no]").onclick = () => { gate.hidden = true; };
    }

    async function micCaption(item) {
      let rec;
      try { rec = new WavRecorder(); await rec.start(); } catch { return; }
      const mic = detail.querySelector(".composer-mic");
      mic.classList.add("rec");
      mic.onclick = async () => {
        mic.classList.remove("rec");
        const blob = await rec.stop();
        try {
          const { transcript } = await ctx.api.transcribeAudio(blob);
          const ta = detail.querySelector(".detail-compose textarea");
          if (ta) { ta.value = transcript; ta.dispatchEvent(new Event("input")); ta.focus(); }
        } catch { /* ignore */ }
      };
    }
  }
}
