import { describe, expect, it } from "vitest";
import catalogueJson from "./__fixtures__/catalogue.json";
import { drillDownUrl, defaultConfig, normalizeConfig } from "./insights";
import { drillInto, isEmptySelection, pickedLabel, selectionFor } from "./drill";
import type { Catalogue, Category, PanelConfig, QueryResult } from "./types";

const catalogue = catalogueJson as unknown as Catalogue;

const CATEGORIES: Category[] = [
  { id: "c-food", name: "Food", is_default: false, color: "#F4A261", keywords: [] },
  { id: "c-rent", name: "Rent", is_default: false, color: "#2A9D8F", keywords: [] },
];

function panel(kind: PanelConfig["chart"], change: Partial<PanelConfig> = {}): PanelConfig {
  return normalizeConfig({ ...defaultConfig(kind), ...change }, catalogue);
}

function result(period = { from: "2026-01-01", to: "2026-12-31" }): QueryResult {
  return { columns: ["x", "value"], rows: [], meta: { chart: "bar" }, period };
}

describe("selectionFor", () => {
  it("turns a clicked category into a category filter", () => {
    expect(selectionFor(panel("bar"), { x: "Food" })).toEqual({ categories: ["Food"] });
  });

  it("turns a clicked merchant, type, weekday and month into their filters", () => {
    expect(selectionFor(panel("bar", { x: { field: "merchant" } }), { x: "Tastybites" })).toEqual({ merchants: ["Tastybites"] });
    expect(selectionFor(panel("bar", { x: { field: "txn_type" } }), { x: "credit" })).toEqual({ type: "credit" });
    expect(selectionFor(panel("bar", { x: { field: "weekday" } }), { x: 0 })).toEqual({ weekdays: [0] });
    expect(selectionFor(panel("bar", { x: { field: "month_of_year" } }), { x: 3 })).toEqual({ months: [3] });
  });

  it("turns a clicked date bucket into the dates it covers", () => {
    const line = panel("line"); // grouped by month
    expect(selectionFor(line, { x: "2026-03-01" })).toEqual({ date: { from: "2026-03-01", to: "2026-03-31" } });
    const weekly = panel("line", { x: { field: "date", granularity: "week" } });
    expect(selectionFor(weekly, { x: "2026-03-02" })).toEqual({ date: { from: "2026-03-02", to: "2026-03-08" } });
  });

  it("adds the colour series to the click", () => {
    const split = panel("bar", { color: { field: "txn_type" } });
    expect(selectionFor(split, { x: "Food", color: "debit" })).toEqual({ categories: ["Food"], type: "debit" });
  });

  it("reads a calendar cell as one day", () => {
    expect(selectionFor(panel("calendar"), { x: "2026-03-05" })).toEqual({ date: { from: "2026-03-05", to: "2026-03-05" } });
  });

  it("reads a heatmap cell as its column and its row", () => {
    const matrix = panel("heatmap"); // weekday by category
    expect(selectionFor(matrix, { x: 3, row: "Food" })).toEqual({ weekdays: [3], categories: ["Food"] });
  });

  it("says nothing for the folded Other bar or a histogram bin", () => {
    expect(isEmptySelection(selectionFor(panel("bar"), { x: "Other" }))).toBe(true);
    expect(isEmptySelection(selectionFor(panel("histogram"), { x: "0.00" }))).toBe(true);
    expect(isEmptySelection(selectionFor(panel("bar"), { x: null }))).toBe(true);
  });
});

describe("pickedLabel", () => {
  it("writes a click the way the chart labels it", () => {
    expect(pickedLabel(panel("bar"), { x: "Food" })).toBe("Food");
    expect(pickedLabel(panel("line"), { x: "2026-03-01" })).toBe("Mar 2026");
    expect(pickedLabel(panel("bar", { color: { field: "txn_type" } }), { x: "Food", color: "debit" })).toContain("Food");
  });

  it("leaves out the folded Other", () => {
    expect(pickedLabel(panel("bar"), { x: "Other" })).toBe("");
  });
});

describe("drillInto", () => {
  it("goes from a month to its weeks, inside that month only", () => {
    const step = drillInto(panel("line"), result(), { x: "2026-03-01" }, CATEGORIES, catalogue);
    expect(step?.label).toBe("Mar 2026");
    expect(step?.config.x).toEqual({ field: "date", granularity: "week" });
    expect(step?.config.filters.date).toEqual({ preset: "custom", from: "2026-03-01", to: "2026-03-31" });
  });

  it("goes down one level at a time to a day, and stops there", () => {
    const years = panel("line", { x: { field: "date", granularity: "year" } });
    const quarter = drillInto(years, result(), { x: "2026-01-01" }, CATEGORIES, catalogue)!;
    expect(quarter.config.x?.granularity).toBe("quarter");
    const month = drillInto(quarter.config, result(), { x: "2026-04-01" }, CATEGORIES, catalogue)!;
    expect(month.config.x?.granularity).toBe("month");
    expect(month.config.filters.date).toEqual({ preset: "custom", from: "2026-04-01", to: "2026-06-30" });
    const week = drillInto(month.config, result(), { x: "2026-04-01" }, CATEGORIES, catalogue)!;
    const day = drillInto(week.config, result(), { x: "2026-04-06" }, CATEGORIES, catalogue)!;
    expect(day.config.x?.granularity).toBe("day");
    expect(drillInto(day.config, result(), { x: "2026-04-06" }, CATEGORIES, catalogue)).toBeNull();
  });

  it("stays inside the period the panel shows", () => {
    const years = panel("line", { x: { field: "date", granularity: "year" } });
    const shown = result({ from: "2026-03-10", to: "2026-09-30" });
    const step = drillInto(years, shown, { x: "2026-01-01" }, CATEGORIES, catalogue)!;
    expect(step.config.filters.date).toEqual({ preset: "custom", from: "2026-03-10", to: "2026-09-30" });
  });

  it("stops following the dashboard's grouping, so the parameter can't undo the drill", () => {
    const bound = panel("bar", {
      x: { field: "date", granularity: "month" },
      bind: { granularity: "granularity", limit: "top_n" },
    });
    const step = drillInto(bound, result(), { x: "2026-03-01" }, CATEGORIES, catalogue)!;
    expect(step.config.bind).toEqual({ limit: "top_n" });
    const only = panel("line", { bind: { granularity: "granularity" } });
    expect(drillInto(only, result(), { x: "2026-03-01" }, CATEGORIES, catalogue)!.config.bind).toBeUndefined();
  });

  it("goes from a category to the merchants inside it", () => {
    const step = drillInto(panel("bar"), result(), { x: "Food" }, CATEGORIES, catalogue)!;
    expect(step.label).toBe("Food");
    expect(step.config.x).toEqual({ field: "merchant" });
    expect(step.config.filters.categories).toEqual(["c-food"]);
  });

  it("matches the category name ignoring case", () => {
    expect(drillInto(panel("bar"), result(), { x: "food" }, CATEGORIES, catalogue)?.config.filters.categories).toEqual(["c-food"]);
  });

  it("drops a calculation that needs a date axis when the axis stops being a date", () => {
    const calc = { ...panel("bar"), calc: { type: "moving_average" as const, window: 3 } };
    const step = drillInto(calc, result(), { x: "Food" }, CATEGORIES, catalogue)!;
    expect(step.config.calc).toBeUndefined();
    const share = { ...panel("bar"), calc: { type: "percent_of_total" as const } };
    expect(drillInto(share, result(), { x: "Food" }, CATEGORIES, catalogue)!.config.calc).toEqual({ type: "percent_of_total" });
  });

  it("has nowhere to go from the folded Other, an unknown category or a merchant", () => {
    expect(drillInto(panel("bar"), result(), { x: "Other" }, CATEGORIES, catalogue)).toBeNull();
    expect(drillInto(panel("bar"), result(), { x: "Pets" }, CATEGORIES, catalogue)).toBeNull();
    expect(drillInto(panel("bar", { x: { field: "merchant" } }), result(), { x: "Tastybites" }, CATEGORIES, catalogue)).toBeNull();
  });

  it("does not drill a chart without a categorical or date axis", () => {
    expect(drillInto(panel("calendar"), result(), { x: "2026-03-05" }, CATEGORIES, catalogue)).toBeNull();
    expect(drillInto(panel("histogram"), result(), { x: "0.00" }, CATEGORIES, catalogue)).toBeNull();
    expect(drillInto(panel("bar", { x: { field: "weekday" } }), result(), { x: 1 }, CATEGORIES, catalogue)).toBeNull();
  });

  it("does not change the config it was given", () => {
    const original = panel("line");
    const before = JSON.stringify(original);
    drillInto(original, result(), { x: "2026-03-01" }, CATEGORIES, catalogue);
    expect(JSON.stringify(original)).toBe(before);
  });
});

describe("the link to the Transactions page", () => {
  it("opens one day for a calendar cell", () => {
    const url = drillDownUrl(panel("calendar"), result(), panel("calendar").filters, { x: "2026-03-05" }, CATEGORIES);
    expect(url).toContain("from=2026-03-05");
    expect(url).toContain("to=2026-03-05");
  });

  it("uses a heatmap cell's row as well as its column", () => {
    const url = drillDownUrl(panel("heatmap"), result(), panel("heatmap").filters, { x: 3, row: "Food" }, CATEGORIES);
    expect(url).toContain("category=c-food");
  });
});
