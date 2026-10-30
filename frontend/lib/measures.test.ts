import { describe, expect, it } from "vitest";
import catalogueJson from "./__fixtures__/catalogue.json";
import { pickedLabel } from "./drill";
import {
  axisSides,
  calcAllowed,
  defaultConfig,
  normalizeConfig,
  seriesConfig,
  seriesName,
  seriesOf,
  unitOf,
} from "./insights";
import type { Catalogue, MeasureSpec, PanelConfig } from "./types";

const catalogue = catalogueJson as unknown as Catalogue;

const SPEND: MeasureSpec = { measure: "spend", agg: "sum" };
const INCOME: MeasureSpec = { measure: "income", agg: "sum" };
const RATE: MeasureSpec = {
  measure: "formula",
  agg: "avg",
  formula: { expression: "net / income * 100", as: "percent" },
};

function line(change: Partial<PanelConfig> = {}): PanelConfig {
  return normalizeConfig({ ...defaultConfig("line"), y: SPEND, also: [INCOME], ...change }, catalogue);
}

describe("seriesOf", () => {
  it("lists the first measure, then the others", () => {
    expect(seriesOf(line()).map((y) => y.measure)).toEqual(["spend", "income"]);
  });

  it("is one measure on an ordinary panel", () => {
    expect(seriesOf({ y: SPEND })).toEqual([SPEND]);
  });
});

describe("seriesName", () => {
  it("uses the measure's own label", () => {
    expect(seriesName([SPEND, INCOME], 1)).toBe("Income");
  });

  it("prefers the name the user gave", () => {
    expect(seriesName([{ ...SPEND, label: " Out " }], 0)).toBe("Out");
  });

  it("numbers formulas only when there are several", () => {
    expect(seriesName([SPEND, RATE], 1)).toBe("Calculated field");
    expect(seriesName([RATE, { ...RATE }], 1)).toBe("Calculated field 2");
  });
});

describe("seriesConfig", () => {
  it("gives the panel as if it showed only that measure", () => {
    const single = seriesConfig(line(), 1);
    expect(single.y.measure).toBe("income");
    expect(single.also).toBeUndefined();
  });

  it("leaves an ordinary panel as it is", () => {
    expect(seriesConfig(defaultConfig("bar"), 0).y.measure).toBe("spend");
  });
});

describe("unitOf", () => {
  it("reads each kind of measure", () => {
    expect(unitOf({ y: SPEND })).toBe("money");
    expect(unitOf({ y: { measure: "count", agg: "sum" } })).toBe("number");
    expect(unitOf({ y: RATE })).toBe("percent");
  });

  it("follows a calculation that turns values into percentages", () => {
    expect(unitOf({ y: SPEND, calc: { type: "percent_of_total" } })).toBe("percent");
  });
});

describe("axisSides", () => {
  it("needs one axis for one unit", () => {
    expect(axisSides(["money", "money"])).toEqual([0, 0]);
  });

  it("keeps money on the left wherever it comes", () => {
    expect(axisSides(["percent", "money"])).toEqual([1, 0]);
  });

  it("uses the first unit when there is no money", () => {
    expect(axisSides(["number", "percent"])).toEqual([0, 1]);
  });

  it("puts everything that isn't money on the right", () => {
    expect(axisSides(["money", "percent", "number"])).toEqual([0, 1, 1]);
  });
});

describe("normalizeConfig", () => {
  it("drops extra measures on a chart that shows one", () => {
    expect(line({ chart: "pie", x: { field: "category" } }).also).toBeUndefined();
  });

  it("keeps a chart to the limit", () => {
    const many = Array.from({ length: catalogue.series.max_extra + 3 }, () => INCOME);
    expect(line({ also: many }).also).toHaveLength(catalogue.series.max_extra);
  });

  it("clears an empty list, so an ordinary panel stays ordinary", () => {
    expect(line({ also: [] }).also).toBeUndefined();
  });

  it("applies each measure's rules", () => {
    const [extra] = line({ also: [{ measure: "balance", agg: "sum" }] }).also ?? [];
    expect(extra.agg).toBe("last");
  });

  it("fills in a new formula", () => {
    const [extra] = line({ also: [{ measure: "formula", agg: "sum" }] }).also ?? [];
    expect(extra.agg).toBe(catalogue.formula.agg);
    expect(extra.formula?.expression).toBeTruthy();
  });

  it("keeps names, and cuts one that is too long", () => {
    const named = line({ y: { ...SPEND, label: "x".repeat(99) } });
    expect(named.y.label).toHaveLength(catalogue.series.max_label);
  });

  it("removes a calculation that doesn't suit a new measure", () => {
    const config = line({ calc: { type: "running_total" } });
    expect(config.calc?.type).toBe("running_total");
    expect(line({ calc: { type: "running_total" }, also: [{ measure: "balance", agg: "last" }] }).calc).toBeUndefined();
  });

  it("keeps a colour split beside several measures", () => {
    expect(line({ color: { field: "category" } }).color?.field).toBe("category");
  });
});

describe("calcAllowed", () => {
  it("checks every measure", () => {
    const config = line({ also: [RATE] });
    expect(calcAllowed(config, catalogue, "running_total")).toBe(false);
    expect(calcAllowed(line(), catalogue, "running_total")).toBe(true);
  });
});

describe("formulas on more charts", () => {
  it.each(["pie", "donut", "calendar", "heatmap"] as const)("keeps a formula on a %s", (chart) => {
    const config = normalizeConfig({ ...defaultConfig(chart), y: RATE }, catalogue);
    expect(config.y.measure).toBe("formula");
  });

  it("swaps a formula out on a histogram", () => {
    expect(normalizeConfig({ ...defaultConfig("histogram"), y: RATE }, catalogue).y.measure).not.toBe("formula");
  });
});

describe("pickedLabel", () => {
  it("names the measure clicked", () => {
    const config = line({ x: { field: "date", granularity: "month" } });
    expect(pickedLabel(config, { x: "2026-03-01", series: 1 })).toContain("Income");
  });
});
