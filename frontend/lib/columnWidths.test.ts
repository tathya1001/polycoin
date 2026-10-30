import { describe, expect, it } from "vitest";
import { arrowStep, clampWidth, defaultWidths, parseWidths, totalWidth, type ColumnSpec } from "./columnWidths";

const COLUMNS: ColumnSpec[] = [
  { key: "pick", width: 48 },
  { key: "name", width: 200, min: 110 },
  { key: "notes", width: 130, min: 90 },
];

describe("clampWidth", () => {
  it("keeps a column above its minimum", () => {
    expect(clampWidth(COLUMNS[1], 20)).toBe(110);
  });

  it("stops a slip of the mouse from making a huge column", () => {
    expect(clampWidth(COLUMNS[1], 5000)).toBe(800);
  });

  it("rounds to whole pixels", () => {
    expect(clampWidth(COLUMNS[1], 150.6)).toBe(151);
  });

  it("never changes a column that can't be resized", () => {
    expect(clampWidth(COLUMNS[0], 300)).toBe(48);
  });
});

describe("parseWidths", () => {
  it("uses the defaults when nothing was saved", () => {
    expect(parseWidths(null, COLUMNS)).toEqual(defaultWidths(COLUMNS));
  });

  it("restores what was saved", () => {
    expect(parseWidths('{"name":240}', COLUMNS).name).toBe(240);
  });

  it("survives damage", () => {
    expect(parseWidths("{not json", COLUMNS)).toEqual(defaultWidths(COLUMNS));
    expect(parseWidths("null", COLUMNS)).toEqual(defaultWidths(COLUMNS));
    expect(parseWidths('{"name":"wide"}', COLUMNS).name).toBe(200);
  });

  it("applies today's limits to an old value", () => {
    expect(parseWidths('{"name":3}', COLUMNS).name).toBe(110);
  });

  it("ignores a column that no longer exists", () => {
    expect(parseWidths('{"gone":300}', COLUMNS)).toEqual(defaultWidths(COLUMNS));
  });
});

describe("totalWidth", () => {
  it("adds up the columns shown", () => {
    expect(totalWidth(COLUMNS, { pick: 48, name: 300, notes: 100 })).toBe(448);
  });
});

describe("arrowStep", () => {
  it("moves with the left and right arrows only", () => {
    expect(arrowStep("ArrowLeft")).toBeLessThan(0);
    expect(arrowStep("ArrowRight")).toBeGreaterThan(0);
    expect(arrowStep("Enter")).toBe(0);
  });
});
