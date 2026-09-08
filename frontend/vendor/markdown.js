// Minimal, dependency-free Markdown -> HTML. Local-first: no library, no CDN.
// Handles headings, bullet/ordered lists, bold/italic/code, fenced blocks
// (mermaid tagged), blockquotes, simple pipe tables, links (non-local hrefs
// drop to plain text), and paragraphs. HTML-escaped first.

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) =>
      /^(#|\.|\/)/.test(u) || /^https?:\/\/(127\.0\.0\.1|localhost)/.test(u)
        ? `<a href="${esc(u)}">${esc(t)}</a>`
        : esc(t));
}

function tableBlock(lines) {
  const rows = lines.map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
  const head = rows[0];
  const body = rows.slice(2);
  const th = head.map((c) => `<th>${inline(c)}</th>`).join("");
  const trs = body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`;
}

export function renderMarkdown(src) {
  const lines = String(src).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0, list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };

  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      closeList();
      const lang = fence[1];
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      const body = esc(buf.join("\n"));
      out.push(lang === "mermaid"
        ? `<pre class="mermaid-src" data-note="diagram">${body}</pre>`
        : `<pre class="code"><code>${body}</code></pre>`);
      continue;
    }
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }

    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?[\s:-]+\|[\s:|-]*$/.test(lines[i + 1] || "")) {
      closeList();
      const buf = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) buf.push(lines[i++]);
      out.push(tableBlock(buf));
      continue;
    }

    const bq = line.match(/^>\s?(.*)$/);
    if (bq) { closeList(); out.push(`<blockquote>${inline(bq[1])}</blockquote>`); i++; continue; }

    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ul || ol) {
      const want = ul ? "ul" : "ol";
      if (list !== want) { closeList(); list = want; out.push(`<${want}>`); }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      i++; continue;
    }

    if (!line.trim()) { closeList(); i++; continue; }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
    i++;
  }
  closeList();
  return out.join("\n");
}
