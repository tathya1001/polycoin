import { describe, expect, it } from "vitest";
import catalogueJson from "@/lib/__fixtures__/catalogue.json";
import { defaultConfig, normalizeConfig } from "@/lib/insights";
import type { Catalogue, FormatOptions, PanelConfig, QueryResult } from "@/lib/types";
import { CHART_LOOKS } from "@/lib/theme";
import { escapeHtml, legendPosition, resolveColor, seriesSwatches, toOption } from "./toOption";

const catalogue = catalogueJson as unknown as Catalogue;

const FORMAT: FormatOptions = { labels: false, number: "auto", legend: "auto", axis: { min: null, max: null } };

function chart(kind: PanelConfig["chart"], format: Partial<FormatOptions> = {}, change: Partial<PanelConfig> = {}) {
  const config = normalizeConfig({ ...defaultConfig(kind), ...change }, catalogue);
  return { ...config, format: { ...FORMAT, ...format } };
}

function result(columns: string[], rows: (string | null)[][]): QueryResult {
  return { columns, rows, meta: { chart: "bar" }, period: { from: "2026-01-01", to: "2026-03-31" } };
}

const BARS = result(["x", "value"], [["Food", "12000.50"], ["Rent", "22000.00"]]);

describe("several measures on one chart", () => {
  const SPEND = { measure: "spend" as const, agg: "sum" as const };
  const INCOME = { measure: "income" as const, agg: "sum" as const };
  const RATE = {
    measure: "formula" as const,
    agg: "avg" as const,
    formula: { expression: "net / income * 100", as: "percent" as const },
    label: "Savings",
  };
  const months = ["2026-01-01", "2026-02-01"];
  const measured = (count: number) =>
    result(
      ["x", "series", "value"],
      Array.from({ length: count }, (_, series) => months.map((x) => [x, String(series), "10.00"])).flat(),
    );
  const split = result(
    ["x", "series", "color", "value"],
    [
      ["2026-01-01", "0", "Food", "10.00"],
      ["2026-01-01", "0", "Rent", "20.00"],
      ["2026-01-01", "1", "Food", "30.00"],
      ["2026-01-01", "1", "Rent", "40.00"],
    ],
  );
  const lineOf = (change: Partial<PanelConfig>) => chart("line", {}, { y: SPEND, also: [INCOME], ...change });
  const seriesIn = (built: ReturnType<typeof toOption>) =>
    built.option.series as { name: string; lineStyle?: { type: unknown }; stack?: string; yAxisIndex?: number; xAxisIndex?: number; itemStyle?: { opacity?: number } }[];

  it("draws one series per measure, in the measure's name", () => {
    const built = toOption(lineOf({}), measured(2));
    expect(seriesIn(built).map((item) => item.name)).toEqual(["Spend", "Income"]);
    expect(built.keys?.measures).toEqual([0, 1]);
  });

  it("shows a legend without being asked", () => {
    expect(toOption(lineOf({}), measured(2)).option.legend).toBeTruthy();
  });

  it("keeps one axis when the units match", () => {
    const built = toOption(lineOf({}), measured(2));
    expect(Array.isArray(built.option.yAxis)).toBe(false);
    expect(seriesIn(built)[1].yAxisIndex).toBeUndefined();
  });

  it("adds a right axis when the units differ, and says so in the legend", () => {
    const built = toOption(lineOf({ also: [RATE] }), measured(2));
    expect(Array.isArray(built.option.yAxis)).toBe(true);
    expect(seriesIn(built)[1]).toMatchObject({ name: "Savings (right axis)", yAxisIndex: 1 });
    expect(seriesIn(built)[0].yAxisIndex).toBe(0);
  });

  it("moves the second axis to the top of horizontal bars", () => {
    const config = chart("bar", {}, { y: SPEND, also: [RATE], orientation: "horizontal" });
    const built = toOption(config, measured(2));
    expect(Array.isArray(built.option.xAxis)).toBe(true);
    expect(seriesIn(built)[1].xAxisIndex).toBe(1);
  });

  it("gives each line its own unit in the tooltip", () => {
    const built = toOption(lineOf({ also: [RATE] }), measured(2));
    const [money, percent] = built.option.series as { tooltip: { valueFormatter: (value: number) => string } }[];
    expect(money.tooltip.valueFormatter(10)).toContain("₹");
    expect(percent.tooltip.valueFormatter(10)).toContain("%");
  });

  it("can set a colour for one measure", () => {
    const config = { ...lineOf({}), series_colors: { m1: "#123456" } };
    const swatches = seriesSwatches(config, measured(2), new Map());
    expect(swatches.map((swatch) => swatch.key)).toEqual(["m0", "m1"]);
    expect(swatches[1].label).toBe("Income");
    expect(swatches[1].color).toBe(CHART_LOOKS.classic.series("#123456"));
  });

  it("draws every measure and colour together", () => {
    const built = toOption(lineOf({ color: { field: "category" } }), split);
    expect(seriesIn(built).map((item) => item.name)).toEqual(["Spend · Food", "Spend · Rent", "Income · Food", "Income · Rent"]);
    expect(built.keys?.colors).toEqual(["Food", "Rent", "Food", "Rent"]);
    expect(built.keys?.measures).toEqual([0, 0, 1, 1]);
  });

  it("tells measures apart by dash when colour means the field", () => {
    const lines = seriesIn(toOption(lineOf({ color: { field: "category" } }), split));
    expect(lines[0].lineStyle?.type).toBe("solid");
    expect(lines[2].lineStyle?.type).toBe("dashed");
  });

  it("gives bars a lighter shade for later measures", () => {
    const config = chart("bar", {}, {
      y: SPEND,
      also: [INCOME],
      x: { field: "date", granularity: "month" },
      color: { field: "category" },
    });
    const bars = seriesIn(toOption(config, split));
    expect(bars[0].itemStyle?.opacity).toBe(1);
    expect(bars[2].itemStyle?.opacity).toBeLessThan(1);
  });

  it("keeps stacks within one measure", () => {
    const config = chart("bar", {}, {
      y: SPEND,
      also: [INCOME],
      x: { field: "date", granularity: "month" },
      color: { field: "category" },
      stacked: true,
    });
    expect(seriesIn(toOption(config, split)).map((item) => item.stack)).toEqual(["total-0", "total-0", "total-1", "total-1"]);
  });

  it("lists colours by the field when split", () => {
    const swatches = seriesSwatches(lineOf({ color: { field: "category" } }), split, new Map());
    expect(swatches.map((swatch) => swatch.key)).toEqual(["Food", "Rent"]);
  });
});

describe("a data source's colour", () => {
  const colors = new Map([
    ["oakbank", "#111111"],
    ["source:oakbank", "#222222"],
  ]);

  it("is used when the chart is split by source, even if a category has the same name", () => {
    const line = resolveColor("OakBank", 0, "data_source", { series_colors: {} }, colors, CHART_LOOKS.classic);
    expect(line).toBe(CHART_LOOKS.classic.series("#222222"));
  });

  it("gives way to the panel's own colour", () => {
    const own = { series_colors: { OakBank: "#333333" } };
    expect(resolveColor("OakBank", 0, "data_source", own, colors, CHART_LOOKS.classic)).toBe(
      CHART_LOOKS.classic.series("#333333"),
    );
  });
});
const SPLIT = result(["x", "color", "value"], [["Food", "credit", "5"], ["Food", "debit", "7"]]);
const PIE = result(["x", "value"], [["Food", "30"], ["Rent", "70"]]);
const HISTOGRAM = result(["start", "end", "count"], [["0.00", "100.00", "4"], ["100.00", "200.00", "1"]]);

// ECharts' option types are wide unions; the tests only look at the parts they set.
/* eslint-disable @typescript-eslint/no-explicit-any */
const series = (config: PanelConfig, data: QueryResult): any[] => (toOption(config, data).option as any).series;
const option = (config: PanelConfig, data: QueryResult): any => toOption(config, data).option;

describe("defaults", () => {
  it("draw a plain bar chart: no labels, an automatic legend, no bounds", () => {
    const plain = chart("bar");
    expect(series(plain, BARS)[0].label).toBeUndefined();
    expect(option(plain, BARS).legend).toBeUndefined();
    expect(option(plain, BARS).yAxis.min).toBeUndefined();
    expect(option(plain, BARS).yAxis.max).toBeUndefined();
  });

  it("treat a config saved before formatting existed as the defaults", () => {
    const { format, ...old } = chart("bar"); // as saved before formatting existed
    expect(format).toBeDefined();
    expect(option(old, SPLIT).legend).toEqual({ type: "scroll", top: 0 }); // a split shows its legend on top
  });
});

describe("labels", () => {
  it("write the value on each bar, in full unless short numbers are chosen", () => {
    const label = series(chart("bar", { labels: true }), BARS)[0].label;
    expect(label).toMatchObject({ show: true, position: "top" });
    expect(label.formatter({ value: 12000.5 })).toBe("₹12,000.50");

    const short = series(chart("bar", { labels: true, number: "compact" }), BARS)[0].label;
    expect(short.formatter({ value: 12000.5 })).toBe("₹12K");
  });

  it("sit beside horizontal bars and inside stacked ones", () => {
    expect(series(chart("bar", { labels: true }, { orientation: "horizontal" }), BARS)[0].label.position).toBe("right");
    const stacked = chart("bar", { labels: true }, { color: { field: "txn_type" }, stacked: true });
    expect(series(stacked, SPLIT)[0].label.position).toBe("inside");
  });

  it("show a missing value as a dash", () => {
    const label = series(chart("bar", { labels: true }), BARS)[0].label;
    expect(label.formatter({ value: null })).toBe("–");
  });

  it("add the value to a pie slice's share", () => {
    const [pie] = series(chart("pie", { labels: true }), PIE);
    expect(pie.label.formatter({ value: 30, percent: 30 })).toBe("₹30.00 (30%)");
    // The old default, in the mode's text colour with no halo (ECharts' own smears on dark).
    expect(series(chart("pie"), PIE)[0].label).toEqual({
      formatter: "{d}%",
      color: "#111111",
      textBorderColor: "transparent",
      textBorderWidth: 0,
    });
  });

  it("show a histogram's counts", () => {
    expect(series(chart("histogram", { labels: true }), HISTOGRAM)[0].label).toEqual({ show: true, position: "top" });
  });
});

describe("number style", () => {
  it("auto: short numbers on the axis, full in the tooltip", () => {
    const o = option(chart("bar"), BARS);
    expect(o.yAxis.axisLabel.formatter(100000)).toBe("₹1L");
    expect(o.tooltip.valueFormatter(100000)).toBe("₹1,00,000.00");
  });

  it("full: written out on the axis too", () => {
    expect(option(chart("bar", { number: "full" }), BARS).yAxis.axisLabel.formatter(100000)).toBe("₹1,00,000");
  });

  it("compact: short in the tooltip as well", () => {
    expect(option(chart("bar", { number: "compact" }), BARS).tooltip.valueFormatter(100000)).toBe("₹1L");
  });

  it("leave percentages and counts alone", () => {
    const share = chart("bar", { number: "compact" }, { calc: { type: "percent_of_total" } });
    expect(option(share, BARS).yAxis.axisLabel.formatter(12.5)).toBe("12.5%");
    const counts = chart("bar", { number: "full" }, { y: { measure: "count", agg: "sum" } });
    expect(option(counts, BARS).yAxis.axisLabel.formatter(1234)).toBe("1,234");
  });
});

describe("legend", () => {
  it("auto shows it only for a split, on top", () => {
    expect(legendPosition(chart("bar"), false, "top")).toBeNull();
    expect(legendPosition(chart("bar"), true, "top")).toBe("top");
  });

  it("can be forced, moved or hidden", () => {
    const split = { color: { field: "txn_type" } } as const;
    expect(option(chart("bar", { legend: "bottom" }, split), SPLIT).legend).toEqual({ type: "scroll", bottom: 0 });
    expect(option(chart("bar", { legend: "none" }, split), SPLIT).legend).toBeUndefined();
    expect(option(chart("bar", { legend: "top" }), BARS).legend).toEqual({ type: "scroll", top: 0 }); // single series
  });

  it("makes room for itself", () => {
    const split = { color: { field: "txn_type" } } as const;
    expect(option(chart("bar", { legend: "right" }, split), SPLIT).grid).toMatchObject({ right: 120, top: 16, bottom: 8 });
    expect(option(chart("bar", { legend: "bottom" }, split), SPLIT).grid).toMatchObject({ right: 16, top: 16, bottom: 36 });
    expect(option(chart("bar", {}, split), SPLIT).grid).toMatchObject({ top: 36, bottom: 8 }); // as before
  });

  it("pie: bottom by default, movable, and the pie shifts to make room", () => {
    expect(option(chart("pie"), PIE).legend).toEqual({ type: "scroll", bottom: 0 });
    expect(option(chart("pie", { legend: "none" }), PIE).legend).toBeUndefined();
    const right = option(chart("pie", { legend: "right" }), PIE);
    expect(right.legend).toMatchObject({ orient: "vertical", right: 0 });
    expect(right.series[0].center[0]).toBe("40%");
  });
});

describe("axis bounds", () => {
  it("set the value axis, either end or both", () => {
    expect(option(chart("line", { axis: { min: 0, max: null } }), BARS).yAxis).toMatchObject({ min: 0 });
    expect(option(chart("line", { axis: { min: 0, max: null } }), BARS).yAxis).not.toHaveProperty("max");
    const both = option(chart("bar", { axis: { min: 10, max: 500 } }), BARS);
    expect(both.yAxis).toMatchObject({ min: 10, max: 500 });
  });

  it("apply to the value axis of a horizontal bar chart, which is x", () => {
    const horizontal = option(chart("bar", { axis: { min: 5, max: null } }, { orientation: "horizontal" }), BARS);
    expect(horizontal.xAxis).toMatchObject({ type: "value", min: 5 });
    expect(horizontal.yAxis.type).toBe("category");
  });
});

describe("heatmaps", () => {
  const CALENDAR = {
    ...result(["x", "value"], [["2026-03-02", "15.00"], ["2026-03-09", "7.00"]]),
    meta: { chart: "calendar" as const },
    period: { from: "2026-03-01", to: "2026-03-31" },
  };
  const MATRIX: QueryResult = {
    ...result(["x", "row", "value"], [["0", "Food", "35.00"], ["1", "Bills", "7.00"]]),
    axes: { x: [0, 1, 2], rows: ["Food", "Bills"] },
  };
  // In the real result x is a number; the fixture's string rows are what JSON gives for a date.
  MATRIX.rows = [[0, "Food", "35.00"], [1, "Bills", "7.00"]] as unknown as QueryResult["rows"];

  it("a calendar covers the period and plots a value for each day with data", () => {
    const o = option(chart("calendar"), CALENDAR);
    expect(o.calendar.range).toEqual(["2026-03-01", "2026-03-31"]);
    expect(o.series[0]).toMatchObject({ type: "heatmap", coordinateSystem: "calendar" });
    expect(o.series[0].data).toEqual([["2026-03-02", 15], ["2026-03-09", 7]]);
    expect(o.calendar.dayLabel.firstDay).toBe(1); // weeks start on Monday, as everywhere else
  });

  it("scales the colours from the smallest value to the largest", () => {
    const scale = option(chart("calendar"), CALENDAR).visualMap;
    expect([scale.min, scale.max]).toEqual([7, 15]);
    expect(scale.inRange.color).toEqual(["#EAF2FC", "#2A78D6", "#12407A"]);
  });

  it("uses a symmetric orange-to-blue scale when values go below zero", () => {
    const net = { ...CALENDAR, rows: [["2026-03-02", "-40.00"], ["2026-03-03", "10.00"]] };
    const scale = option(chart("calendar", {}, { y: { measure: "net", agg: "sum" } }), net).visualMap;
    expect([scale.min, scale.max]).toEqual([-40, 40]);
    expect(scale.inRange.color[0]).toBe("#EB6834");
  });

  it("shows an empty calendar's scale without breaking", () => {
    const empty = { ...CALENDAR, rows: [] };
    const scale = option(chart("calendar"), empty).visualMap;
    expect(scale.max).toBeGreaterThan(scale.min);
  });

  it("a matrix places each cell by its position on the two axes", () => {
    const o = option(chart("heatmap", {}, {}), MATRIX);
    expect(o.xAxis.data).toHaveLength(3);
    expect(o.yAxis.data).toEqual(["Food", "Bills"]);
    expect(o.series[0].data).toEqual([[0, 0, 35], [1, 1, 7]]);
    expect(o.yAxis.inverse).toBe(true); // first row at the top
  });

  it("a matrix skips a cell whose x or row isn't on an axis", () => {
    const stray = { ...MATRIX, rows: [[0, "Food", "1"], [9, "Food", "2"], [0, "Nope", "3"]] as unknown as QueryResult["rows"] };
    expect(option(chart("heatmap"), stray).series[0].data).toEqual([[0, 0, 1]]);
  });

  it("writes values in the cells only when asked", () => {
    expect(option(chart("heatmap"), MATRIX).series[0].label).toBeUndefined();
    const label = option(chart("heatmap", { labels: true }), MATRIX).series[0].label;
    expect(label.formatter({ value: [0, 0, 35] })).toBe("₹35.00");
  });

  it("a click on a calendar day or a matrix cell is traced back to its raw keys", () => {
    expect(toOption(chart("calendar"), CALENDAR).keys?.cells).toEqual([{ x: "2026-03-02" }, { x: "2026-03-09" }]);
    expect(toOption(chart("heatmap"), MATRIX).keys?.cells).toEqual([
      { x: 0, row: "Food" },
      { x: 1, row: "Bills" },
    ]);
  });

  it("keeps a matrix cell's keys lined up with its data when a stray cell is skipped", () => {
    const stray = { ...MATRIX, rows: [[9, "Food", "2"], [1, "Bills", "7"]] as unknown as QueryResult["rows"] };
    const built = toOption(chart("heatmap"), stray);
    expect((built.option as any).series[0].data).toEqual([[1, 1, 7]]);
    expect(built.keys?.cells).toEqual([{ x: 1, row: "Bills" }]);
  });

  it("neither heatmap chart has series colours to edit", () => {
    expect(seriesSwatches(chart("calendar"), CALENDAR, new Map())).toEqual([]);
    expect(seriesSwatches(chart("heatmap"), MATRIX, new Map())).toEqual([]);
  });

  it("escapes every piece of a tooltip, so a hostile category name stays text", () => {
    const hostile = '<img src=x onerror=alert(1)> & "q"';
    const o = option(chart("heatmap"), {
      ...MATRIX,
      axes: { x: [0, 1, 2], rows: [hostile, "Bills"] },
      rows: [[0, hostile, "35.00"]] as unknown as QueryResult["rows"],
    });
    const html: string = o.tooltip.formatter({ value: [0, 0, 35] });
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot;");
    expect(html).toContain("<b>₹35.00</b>"); // the only markup is ours
  });
});

describe("escapeHtml", () => {
  it.each([
    ["<script>", "&lt;script&gt;"],
    ["a & b", "a &amp; b"],
    [`"it's"`, "&quot;it&#39;s&quot;"],
    ["plain", "plain"],
  ])("%j -> %j", (input, expected) => {
    expect(escapeHtml(input)).toBe(expected);
  });
});

describe("highlight", () => {
  const opacities = (data: any[]) => data.map((item) => item.itemStyle.opacity);

  it("dims every bar but the picked one", () => {
    const data = series(chart("bar"), BARS)[0].data;
    expect(opacities(data)).toEqual([1, 1]); // nothing picked: nothing dimmed
    const dimmed = (toOption(chart("bar"), BARS, new Map(), "Rent").option as any).series[0].data;
    expect(opacities(dimmed)).toEqual([0.3, 1]);
  });

  it("dims the bars of a date axis and keeps the series colour", () => {
    const months = result(["x", "value"], [["2026-01-01", "5"], ["2026-02-01", "6"]]);
    const built = toOption(chart("bar", {}, { x: { field: "date", granularity: "month" } }), months, new Map(), "2026-02-01");
    const data = (built.option as any).series[0].data;
    expect(opacities(data)).toEqual([0.3, 1]);
    expect(data[0].itemStyle.color).toBe(data[1].itemStyle.color);
  });

  it("dims the slices of a pie", () => {
    const built = toOption(chart("pie"), PIE, new Map(), "Food");
    expect(opacities((built.option as any).series[0].data)).toEqual([1, 0.3]);
  });

  it("leaves a chart alone when nothing is picked", () => {
    const built = toOption(chart("pie"), PIE);
    expect(opacities((built.option as any).series[0].data)).toEqual([1, 1]);
  });
});
