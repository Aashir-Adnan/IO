// Pure snap-grid layout math for the home-screen widget board. An item is
// { id, type, size: "S"|"M"|"L", col, row }; the grid is COLS wide and grows
// downward. Every function returns a new array and never mutates its input.
export const COLS = 4;
export const SIZES = { S: { w: 1, h: 1 }, M: { w: 2, h: 1 }, L: { w: 2, h: 2 } };

export const span = (size) => SIZES[size] || SIZES.S;

const overlaps = (a, b) => {
  const A = span(a.size), B = span(b.size);
  return a.col < b.col + B.w && b.col < a.col + A.w
      && a.row < b.row + B.h && b.row < a.row + A.h;
};

const clampCol = (item) => {
  const { w } = span(item.size);
  return Math.max(0, Math.min(item.col | 0, COLS - w));
};

// Re-pack: the pinned item (the one just moved/resized) keeps its cell, every
// other item floats up as far as it can, then is pushed down past any overlap.
function reflow(items, pinnedId = null) {
  const order = [...items].sort((a, b) =>
    a.id === pinnedId ? -1 : b.id === pinnedId ? 1 : a.row - b.row || a.col - b.col);
  const placed = [];
  for (const it of order) {
    const item = { ...it };
    if (item.id !== pinnedId) {
      while (item.row > 0 && !placed.some((p) => overlaps({ ...item, row: item.row - 1 }, p))) item.row--;
    }
    while (placed.some((p) => overlaps(item, p))) item.row++;
    placed.push(item);
  }
  return items.map((it) => placed.find((p) => p.id === it.id));
}

export function place(layout, widget) {
  const item = { size: "S", ...widget };
  const { w } = span(item.size);
  for (let row = 0; ; row++) {
    for (let col = 0; col <= COLS - w; col++) {
      const cand = { ...item, col, row };
      if (!layout.some((p) => overlaps(cand, p))) return [...layout, cand];
    }
  }
}

export function move(layout, id, col, row) {
  const next = layout.map((it) => {
    if (it.id !== id) return it;
    const moved = { ...it, row: Math.max(0, row | 0) };
    return { ...moved, col: clampCol({ ...moved, col }) };
  });
  return reflow(next, id);
}

export function resize(layout, id, size) {
  const next = layout.map((it) => {
    if (it.id !== id) return it;
    const grown = { ...it, size: SIZES[size] ? size : it.size };
    return { ...grown, col: clampCol(grown) };
  });
  return reflow(next, id);
}

export const remove = (layout, id) => reflow(layout.filter((it) => it.id !== id));

// Repair whatever came back from disk: drop duplicate ids, fix sizes and
// positions, separate overlaps.
export function normalize(layout) {
  const seen = new Set();
  const clean = [];
  for (const raw of layout || []) {
    if (!raw || seen.has(raw.id)) continue;
    seen.add(raw.id);
    const size = SIZES[raw.size] ? raw.size : "S";
    const item = { ...raw, size, row: Math.max(0, raw.row | 0) };
    clean.push({ ...item, col: clampCol({ ...item, col: raw.col }) });
  }
  return reflow(clean);
}
