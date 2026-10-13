// The dashboard grid, as pure functions: no React, no DOM.
//
// The page is 12 columns wide and grows downwards in rows. Every panel is a Box: x and w in
// columns, y and h in rows. The rules match backend/insights/models.py, which also enforces
// them with database constraints:
//   1 <= w <= 12,  x + w <= 12,  2 <= h <= 30
//
// After any move or resize the layout is "settled": the moved box wins its spot, anything
// it lands on is pushed down, then every box floats up as far as it can (vertical
// compaction), so there are never gaps or overlaps.

export const COLS = 12;
export const MIN_H = 2;
export const MAX_H = 30;
export const ROW_HEIGHT = 40; // px per row
export const GAP = 12; // px between panels, both directions

export type Box = { id: string; x: number; y: number; w: number; h: number };

export function collides(a: Box, b: Box): boolean {
  return (
    a.id !== b.id &&
    a.x < b.x + b.w &&
    b.x < a.x + a.w &&
    a.y < b.y + b.h &&
    b.y < a.y + a.h
  );
}

// Top to bottom, then left to right: the order panels are read, and the order they settle.
export function byPosition(a: Box, b: Box): number {
  return a.y - b.y || a.x - b.x;
}

export function bottom(boxes: Box[]): number {
  return boxes.reduce((lowest, box) => Math.max(lowest, box.y + box.h), 0);
}

// Keep a box inside the rules, whatever the pointer did.
export function clampBox(box: Box): Box {
  const w = Math.min(Math.max(Math.round(box.w), 1), COLS);
  const h = Math.min(Math.max(Math.round(box.h), MIN_H), MAX_H);
  const x = Math.min(Math.max(Math.round(box.x), 0), COLS - w);
  const y = Math.max(Math.round(box.y), 0);
  return { ...box, x, y, w, h };
}

// Place `pinned` exactly where it is, push the others down out of its way (and out of each
// other's way), then float everything up. `pinned` is the box being moved or resized.
function settle(boxes: Box[], pinned: Box): Box[] {
  const placed: Box[] = [pinned];
  for (const box of boxes.filter((b) => b.id !== pinned.id).sort(byPosition)) {
    const next = { ...box };
    while (placed.some((other) => collides(next, other))) next.y += 1;
    placed.push(next);
  }
  return compact(placed);
}

// Float every box up as far as it goes without overlapping a box above it.
export function compact(boxes: Box[]): Box[] {
  const placed: Box[] = [];
  for (const box of [...boxes].sort(byPosition)) {
    const next = { ...box };
    while (next.y > 0 && !placed.some((other) => collides({ ...next, y: next.y - 1 }, other))) {
      next.y -= 1;
    }
    while (placed.some((other) => collides(next, other))) next.y += 1;
    placed.push(next);
  }
  return placed;
}

export function moveBox(boxes: Box[], id: string, x: number, y: number): Box[] {
  const box = boxes.find((b) => b.id === id);
  if (!box) return boxes;
  return settle(boxes, clampBox({ ...box, x, y }));
}

export function resizeBox(boxes: Box[], id: string, w: number, h: number): Box[] {
  const box = boxes.find((b) => b.id === id);
  if (!box) return boxes;
  // Resizing grows to the right and down, so the width is limited by where the box starts.
  const width = Math.min(Math.max(Math.round(w), 1), COLS - box.x);
  return settle(boxes, clampBox({ ...box, w: width, h }));
}

// The boxes whose position or size differ from `before`: what the layout PUT must send.
export function changedBoxes(before: Box[], after: Box[]): Box[] {
  const old = new Map(before.map((box) => [box.id, box]));
  return after.filter((box) => {
    const was = old.get(box.id);
    return !was || was.x !== box.x || was.y !== box.y || was.w !== box.w || was.h !== box.h;
  });
}

// --- pixels <-> grid units ------------------------------------------------------

export function columnWidth(containerWidth: number): number {
  return (containerWidth - GAP * (COLS - 1)) / COLS;
}

export function toPixels(box: Box, containerWidth: number) {
  const col = columnWidth(containerWidth);
  return {
    left: box.x * (col + GAP),
    top: box.y * (ROW_HEIGHT + GAP),
    width: box.w * col + (box.w - 1) * GAP,
    height: box.h * ROW_HEIGHT + (box.h - 1) * GAP,
  };
}

// How many whole columns / rows a pointer movement of (dx, dy) pixels is worth.
export function toGridDelta(dx: number, dy: number, containerWidth: number) {
  return {
    cols: Math.round(dx / (columnWidth(containerWidth) + GAP)),
    rows: Math.round(dy / (ROW_HEIGHT + GAP)),
  };
}

export function gridHeight(boxes: Box[]): number {
  const rows = bottom(boxes);
  return rows === 0 ? 0 : rows * (ROW_HEIGHT + GAP) - GAP;
}
