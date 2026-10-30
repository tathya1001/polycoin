// Column widths for a table the user can resize. Pure: no React, no DOM.

export type ColumnSpec = {
  key: string;
  width: number; // the default, in px
  min?: number; // no `min`: the column can't be resized
};

export type Widths = Record<string, number>;

const MAX_WIDTH = 800; // wider than this is a slip of the mouse, and hard to come back from
const KEY_STEP = 16; // px per arrow key press

export function clampWidth(spec: ColumnSpec, width: number): number {
  if (spec.min === undefined) return spec.width;
  return Math.round(Math.min(Math.max(width, spec.min), MAX_WIDTH));
}

export function defaultWidths(columns: ColumnSpec[]): Widths {
  return Object.fromEntries(columns.map((column) => [column.key, column.width]));
}

// What was saved in this browser, checked: it may be damaged, or from when the columns were different.
export function parseWidths(raw: string | null, columns: ColumnSpec[]): Widths {
  const widths = defaultWidths(columns);
  if (!raw) return widths;
  try {
    const saved: unknown = JSON.parse(raw);
    if (typeof saved !== "object" || saved === null) return widths;
    for (const column of columns) {
      const value = (saved as Record<string, unknown>)[column.key];
      if (typeof value === "number" && Number.isFinite(value)) widths[column.key] = clampWidth(column, value);
    }
  } catch {
    // damaged: the defaults are a fine place to start again
  }
  return widths;
}

export function totalWidth(columns: ColumnSpec[], widths: Widths): number {
  return columns.reduce((sum, column) => sum + (widths[column.key] ?? column.width), 0);
}

export function arrowStep(key: string): number {
  if (key === "ArrowLeft") return -KEY_STEP;
  if (key === "ArrowRight") return KEY_STEP;
  return 0;
}
