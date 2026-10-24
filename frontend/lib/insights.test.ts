import { describe, expect, it } from "vitest";
import catalogueJson from "./__fixtures__/catalogue.json";
import {
  BIND_FIELDS,
  baselineText,
  bindingAllowed,
  calcAllowed,
  defaultConfig,
  defaultFormat,
  defaultKpi,
  formatBaseline,
  formatFigure,
  formatValue,
  isPercent,
  kpiTone,
  normalizeConfig,
  usedParameters,
} from "./insights";
import type { Catalogue, FormatOptions, KpiOptions, PanelConfig } from "./types";

// The backend's real catalogue; backend/insights/test_catalogue_contract.py keeps this copy current.
const catalogue = catalogueJson as unknown as Catalogue; // JSON arrays type as number[], not tuples

function draft(change: Partial<PanelConfig>): PanelConfig {
  return normalizeConfig({ ...defaultConfig("line"), ...change }, catalogue);
}

// --- which calculations a draft can use ---------------------------------------------

describe("calcAllowed", () => {
  const types = ["running_total", "percent_of_total", "moving_average", "change"] as const;
  const allowed = (config: PanelConfig) => types.filter((type) => calcAllowed(config, catalogue, type));

  it("allows every calculation on a sum over dates", () => {
    expect(allowed(draft({}))).toEqual(types);
  });

  it("allows only % of total when x isn't a date", () => {
    expect(allowed(normalizeConfig(defaultConfig("bar"), catalogue))).toEqual(["percent_of_total"]);
  });

  it("needs values that add up for a running total or % of total", () => {
    expect(allowed(draft({ y: { measure: "spend", agg: "avg" } }))).toEqual(["moving_average", "change"]);
  });

  it("refuses % of total for a measure that can be negative", () => {
    expect(allowed(draft({ y: { measure: "net", agg: "sum" } }))).toEqual(["running_total", "moving_average", "change"]);
  });

  it("allows nothing on a KPI or a histogram", () => {
    expect(allowed(normalizeConfig(defaultConfig("kpi"), catalogue))).toEqual([]);
    expect(allowed(normalizeConfig(defaultConfig("histogram"), catalogue))).toEqual([]);
  });
});

// --- normalizeConfig keeps a calculation the backend will accept -----------------------

describe("normalizeConfig with a calculation", () => {
  it("stamps the catalogue's spec version", () => {
    expect(draft({}).v).toBe(catalogue.version);
  });

  it("fills in the defaults the backend would", () => {
    expect(draft({ calc: { type: "moving_average" } }).calc).toEqual({ type: "moving_average", window: 3 });
    expect(draft({ calc: { type: "change" } }).calc).toEqual({ type: "change", vs: "previous", as: "percent" });
  });

  it("keeps a window inside the catalogue's limits and drops options a calculation doesn't use", () => {
    const [low, high] = catalogue.limits.window;
    expect(draft({ calc: { type: "moving_average", window: 99 } }).calc?.window).toBe(high);
    expect(draft({ calc: { type: "moving_average", window: 0 } }).calc?.window).toBe(low);
    expect(draft({ calc: { type: "running_total", window: 4, vs: "year_ago" } }).calc).toEqual({ type: "running_total" });
  });

  it("drops a calculation the new chart can't use", () => {
    const withCalc = draft({ calc: { type: "running_total" } });
    expect(normalizeConfig({ ...withCalc, chart: "kpi" }, catalogue).calc).toBeUndefined();
    // A bar by category: line charts only take dates, so the switch has to change the chart too.
    expect(normalizeConfig({ ...withCalc, chart: "bar", x: { field: "category" } }, catalogue).calc).toBeUndefined();
  });

  it("keeps % of total when x becomes a category", () => {
    const share = draft({ calc: { type: "percent_of_total" } });
    expect(normalizeConfig({ ...share, chart: "bar", x: { field: "category" } }, catalogue).calc).toEqual({
      type: "percent_of_total",
    });
  });
});

// --- how calculated values read ------------------------------------------------------

describe("formatValue", () => {
  const money = { y: { measure: "spend", agg: "sum" } } as const;
  const count = { y: { measure: "count", agg: "sum" } } as const;

  it("shows percentages from % of total and % change", () => {
    expect(formatValue("12.5", { ...money, calc: { type: "percent_of_total" } })).toBe("12.5%");
    expect(formatValue("-3.0", { ...money, calc: { type: "change", as: "percent" } })).toBe("-3%");
    expect(isPercent({ calc: { type: "change", as: "amount" } })).toBe(false);
  });

  it("keeps decimals on an average of counts but not on a plain count", () => {
    expect(formatValue("1.50", { ...count, calc: { type: "moving_average", window: 2 } })).toBe("1.5");
    expect(formatValue("3", count)).toBe("3");
  });

  it("still formats money and the empty value as before", () => {
    expect(formatValue("1234.5", money)).toBe("₹1,234.50");
    expect(formatValue(null, money)).toBe("–");
  });
});

// --- KPI cards -----------------------------------------------------------------------------

describe("normalizeConfig for a KPI", () => {
  const kpiDraft = (change: Partial<PanelConfig>) => normalizeConfig({ ...defaultConfig("kpi"), ...change }, catalogue);

  it("starts a new KPI comparing with the previous period", () => {
    expect(defaultConfig("kpi").kpi).toEqual({ compare: "previous", sparkline: null, direction: "auto", secondary: [] });
  });

  it("gives only KPIs the KPI options", () => {
    expect(normalizeConfig(defaultConfig("bar"), catalogue).kpi).toBeUndefined();
    expect(normalizeConfig({ ...defaultConfig("kpi"), chart: "bar" }, catalogue).kpi).toBeUndefined();
  });

  it("keeps the number of periods only for the average comparison, inside the limits", () => {
    const [low, high] = catalogue.kpi.average_of;
    expect(kpiDraft({ kpi: { ...defaultKpi(), compare: "average" } }).kpi?.average_of).toBe(3);
    expect(kpiDraft({ kpi: { ...defaultKpi(), compare: "average", average_of: 99 } }).kpi?.average_of).toBe(high);
    expect(kpiDraft({ kpi: { ...defaultKpi(), compare: "average", average_of: 1 } }).kpi?.average_of).toBe(low);
    expect(kpiDraft({ kpi: { ...defaultKpi(), compare: "previous", average_of: 5 } }).kpi).not.toHaveProperty("average_of");
  });

  it("drops small figures the measure can't show, duplicates, and anything past the limit", () => {
    const money = { y: { measure: "spend", agg: "sum" } } as const;
    const ok = kpiDraft({ ...money, kpi: { ...defaultKpi(), secondary: ["count", "count", "average", "largest", "share_of_income"] } });
    expect(ok.kpi?.secondary).toEqual(["count", "average", "largest"]); // three at most

    const counts = kpiDraft({ y: { measure: "count", agg: "sum" }, kpi: { ...defaultKpi(), secondary: ["count", "average"] } });
    expect(counts.kpi?.secondary).toEqual(["count"]); // an average needs money

    const avg = kpiDraft({ y: { measure: "spend", agg: "avg" }, kpi: { ...defaultKpi(), secondary: ["share_of_income"] } });
    expect(avg.kpi?.secondary).toEqual([]); // a share needs a sum
  });
});

describe("kpiTone", () => {
  it("auto: spending less is good, and for every other measure more is good", () => {
    expect(kpiTone(-10, { direction: "auto" }, "spend")).toBe("good");
    expect(kpiTone(10, { direction: "auto" }, "spend")).toBe("bad");
    expect(kpiTone(10, { direction: "auto" }, "income")).toBe("good");
    expect(kpiTone(-10, { direction: "auto" }, "net")).toBe("bad");
  });

  it("an explicit direction overrides the measure", () => {
    expect(kpiTone(10, { direction: "down_is_good" }, "income")).toBe("bad");
    expect(kpiTone(10, { direction: "up_is_good" }, "spend")).toBe("good");
  });

  it("no change, or nothing to compare, is neither good nor bad", () => {
    expect(kpiTone(0, { direction: "auto" }, "spend")).toBe("flat");
    expect(kpiTone(null, { direction: "up_is_good" }, "spend")).toBe("flat");
  });
});

describe("KPI text", () => {
  const kpi = (change: Partial<KpiOptions>): KpiOptions => ({ ...defaultKpi(), ...change });

  it("says what the number is compared with", () => {
    expect(baselineText(kpi({ compare: "previous" }), "₹950.00")).toBe("vs ₹950.00 before");
    expect(baselineText(kpi({ compare: "year_ago" }), "₹950.00")).toBe("vs ₹950.00 a year ago");
    expect(baselineText(kpi({ compare: "average", average_of: 6 }), "₹950.00")).toBe(
      "vs an average of ₹950.00 over the 6 periods before",
    );
  });

  it("keeps a decimal on an average of counts only", () => {
    const count = { y: { measure: "count", agg: "sum" } } as const;
    expect(formatBaseline("12.5", { ...count, kpi: kpi({ compare: "average", average_of: 3 }) })).toBe("12.5");
    expect(formatBaseline("12", { ...count, kpi: kpi({ compare: "previous" }) })).toBe("12");
    expect(formatBaseline("950.00", { y: { measure: "spend", agg: "sum" }, kpi: kpi({ compare: "average" }) })).toBe("₹950.00");
  });

  it("formats each small figure", () => {
    expect(formatFigure("count", "1234")).toBe("1,234");
    expect(formatFigure("average", "310.5")).toBe("₹310.50");
    expect(formatFigure("largest", "2400.00")).toBe("₹2,400.00");
    expect(formatFigure("share_of_income", "38.4")).toBe("38.4%");
    expect(formatFigure("average", null)).toBe("–");
  });
});

// --- formatting options --------------------------------------------------------------------

describe("normalizeConfig with formatting", () => {
  const withFormat = (chart: PanelConfig["chart"], format: Partial<FormatOptions>) =>
    normalizeConfig({ ...defaultConfig(chart), format: { ...defaultFormat(), ...format } }, catalogue);

  it("fills in the defaults for charts that have formatting, and none for a KPI", () => {
    expect(normalizeConfig(defaultConfig("bar"), catalogue).format).toEqual(defaultFormat());
    expect(normalizeConfig(defaultConfig("histogram"), catalogue).format).toEqual(defaultFormat());
    expect(normalizeConfig(defaultConfig("kpi"), catalogue).format).toBeUndefined();
  });

  it("resets the options a chart doesn't have: a pie has no axis, a histogram no legend", () => {
    const pie = withFormat("pie", { axis: { min: 0, max: 10 }, legend: "right", labels: true });
    expect(pie.format).toEqual({ labels: true, number: "auto", legend: "right", axis: { min: null, max: null } });
    expect(withFormat("histogram", { legend: "top" }).format?.legend).toBe("auto");
  });

  it("keeps the axis bounds of a chart that has an axis, and drops anything that isn't a number", () => {
    expect(withFormat("line", { axis: { min: 0, max: 5000 } }).format?.axis).toEqual({ min: 0, max: 5000 });
    expect(withFormat("bar", { axis: { min: Number.NaN, max: Infinity } }).format?.axis).toEqual({ min: null, max: null });
  });

  it("falls back to the default for a value the catalogue doesn't offer", () => {
    const odd = withFormat("bar", { number: "percent" as never, legend: "left" as never });
    expect(odd.format).toMatchObject({ number: "auto", legend: "auto" });
  });

  it("drops the formatting when the chart changes to a KPI", () => {
    const bar = withFormat("bar", { labels: true });
    expect(normalizeConfig({ ...bar, chart: "kpi" }, catalogue).format).toBeUndefined();
  });
});

// --- dashboard parameters ---------------------------------------------------------------------

describe("bindings", () => {
  const bar = () => normalizeConfig(defaultConfig("bar"), catalogue);
  const bound = (config: PanelConfig, bind: PanelConfig["bind"]) => normalizeConfig({ ...config, bind }, catalogue);

  it("lists which fields each chart has to follow a parameter", () => {
    const fields = BIND_FIELDS.filter((field) => bindingAllowed(bar(), field));
    expect(fields).toEqual(["limit", "measure"]); // a category bar: no date to group, no KPI, no change
    const line = normalizeConfig(defaultConfig("line"), catalogue);
    expect(BIND_FIELDS.filter((field) => bindingAllowed(line, field))).toEqual(["granularity", "measure"]);
    const kpi = normalizeConfig(defaultConfig("kpi"), catalogue);
    expect(BIND_FIELDS.filter((field) => bindingAllowed(kpi, field))).toEqual(["measure", "compare"]);
    const change = normalizeConfig({ ...defaultConfig("line"), calc: { type: "change" } }, catalogue);
    expect(bindingAllowed(change, "vs")).toBe(true);
  });

  it("keeps a bound field and points it at the parameter the catalogue names", () => {
    expect(bound(bar(), { limit: "top_n", measure: "measure" }).bind).toEqual({ limit: "top_n", measure: "measure" });
  });

  it("forgets a binding the panel can no longer use", () => {
    const line = normalizeConfig(defaultConfig("line"), catalogue);
    const both = bound(line, { granularity: "granularity", measure: "measure" });
    expect(both.bind).toEqual({ granularity: "granularity", measure: "measure" });
    // Group by category instead of by date: there is no date step left to follow.
    const byCategory = normalizeConfig({ ...both, chart: "bar", x: { field: "category" } }, catalogue);
    expect(byCategory.bind).toEqual({ measure: "measure" });
    // Without any binding, there is no bind key at all.
    expect(bound(bar(), {}).bind).toBeUndefined();
    expect(bound(bar(), { granularity: "granularity" }).bind).toBeUndefined();
  });

  it("works out which parameters need a control, in a fixed order, from the panels' bindings", () => {
    const panel = (config: PanelConfig | null) => ({ config });
    const panels = [
      panel(bound(bar(), { measure: "measure" })),
      panel(bound(bar(), { limit: "top_n" })),
      panel(bar()), // follows nothing
      panel(null), // a panel whose saved settings no longer work
      { config: { v: 6, chart: "text", text: "a note" } as const },
    ];
    expect(usedParameters(panels)).toEqual(["top_n", "measure"]);
    expect(usedParameters([panel(bar())])).toEqual([]);
    expect(usedParameters([])).toEqual([]);
  });
});
