// Turns a panel config plus its query result into an ECharts option. Pure: no React, no DOM.
//
// The backend returns "long" rows, one per (x, colour) pair:  [x, value] or [x, colour, value].
// ECharts wants "wide" series, one per colour, each lined up with the x axis, so this pivots.
//
// Text from the user's data (category and merchant names) is only ever passed as plain
// strings. Tooltips use ECharts' default markup, which escapes it; there is deliberately no
// custom HTML formatter anywhere here.

import type { ComposeOption } from "echarts/core";
import type { BarSeriesOption, LineSeriesOption, PieSeriesOption } from "echarts/charts";
import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";
import { FALLBACK_SERIES_COLORS } from "@/lib/colors";
import { MEASURE_LABELS, formatLabel, formatValue, isCountLike } from "@/lib/insights";
import type { Cell, Dimension, PanelConfig, QueryResult } from "@/lib/types";

export type ChartOption = ComposeOption<
  | BarSeriesOption
  | LineSeriesOption
  | PieSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
>;

// What a click on (seriesIndex, dataIndex) refers to, in the backend's raw values.
export type ChartKeys = { x: Cell[]; colors: Cell[] };

export type BuiltChart = { option: ChartOption; keys: ChartKeys | null };

// Category name (lower case) -> "#RRGGBB". Category values in a result are names.
export type CategoryColors = ReadonlyMap<string, string>;

// The key under which a chart with a single series stores its colour in series_colors.
export const SINGLE_SERIES_KEY = "_";

const INK = "#111111";

const toNumber = (value: Cell) => (value === null ? null : Number(value));

const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

function axisFormatter(config: PanelConfig) {
  return (value: number) => (isCountLike(config) ? compact.format(value) : `₹${compact.format(value)}`);
}

function unique(values: Cell[]): Cell[] {
  return [...new Set(values)];
}

// The colour of one series / bar / slice. Most specific wins:
//   1. the panel's own override       (series_colors[key])
//   2. the category's colour          (when the thing being coloured IS a category)
//   3. the default sequence, by position
// `key` is the raw value (a category name, "credit", a month...), or SINGLE_SERIES_KEY.
export function resolveColor(
  key: Cell | typeof SINGLE_SERIES_KEY,
  position: number,
  field: Dimension | undefined,
  config: Pick<PanelConfig, "series_colors">,
  categoryColors: CategoryColors,
): string {
  const text = String(key);
  const override = config.series_colors?.[text];
  if (override) return override;
  if (field === "category" && key !== null) {
    const own = categoryColors.get(text.toLowerCase());
    if (own) return own;
  }
  return FALLBACK_SERIES_COLORS[position % FALLBACK_SERIES_COLORS.length];
}

// Nothing to draw: no rows, or every value is empty or zero.
export function isEmptyResult(config: PanelConfig, result: QueryResult): boolean {
  if (config.chart === "kpi") return false; // a KPI of 0 is still an answer
  if (config.chart === "histogram") return result.rows.length === 0;
  const valueIndex = result.columns.indexOf("value");
  return result.rows.every((row) => {
    const value = row[valueIndex];
    return value === null || Number(value) === 0;
  });
}

// The series a panel will draw, in order, with the colour each currently gets. The editor's
// Colors section lists these so the user can recolour any of them.
export type SeriesSwatch = { key: string; label: string; color: string };

export function seriesSwatches(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors): SeriesSwatch[] {
  if (config.chart === "kpi") return [];
  if (config.chart === "histogram") {
    return [{ key: SINGLE_SERIES_KEY, label: MEASURE_LABELS[config.y.measure], color: resolveColor(SINGLE_SERIES_KEY, 0, undefined, config, categoryColors) }];
  }

  const split = result.columns.includes("color");
  const bySlices = config.chart === "pie" || config.chart === "donut";
  const perBar = config.chart === "bar" && !split && config.x?.field !== "date";

  // What the colours belong to: slices, bars, or the colour-split series.
  let keys: Cell[];
  let field: Dimension | undefined;
  if (split) {
    keys = unique(result.rows.map((row) => row[1]));
    field = config.color?.field;
  } else if (bySlices || perBar) {
    keys = unique(result.rows.map((row) => row[0]));
    field = config.x?.field;
  } else {
    return [
      {
        key: SINGLE_SERIES_KEY,
        label: MEASURE_LABELS[config.y.measure],
        color: resolveColor(SINGLE_SERIES_KEY, 0, undefined, config, categoryColors),
      },
    ];
  }
  return keys.map((key, position) => ({
    key: String(key),
    label: formatLabel(key, field),
    color: resolveColor(key, position, field, config, categoryColors),
  }));
}

function histogramChart(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors): BuiltChart {
  const labels = result.rows.map(([start, end]) => `${compact.format(Number(start))}–${compact.format(Number(end))}`);
  const color = resolveColor(SINGLE_SERIES_KEY, 0, undefined, config, categoryColors);
  return {
    keys: null, // a bin is a range of amounts, which /transactions can't filter on
    option: {
      grid: { left: 8, right: 8, top: 16, bottom: 8 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (value) => `${value} transactions`,
      },
      xAxis: { type: "category", data: labels, name: "₹ amount", nameLocation: "middle", nameGap: 28 },
      yAxis: { type: "value", minInterval: 1 },
      series: [
        {
          type: "bar",
          name: MEASURE_LABELS[config.y.measure],
          data: result.rows.map((row) => Number(row[2])),
          barCategoryGap: "4%",
          itemStyle: { color, borderColor: INK, borderWidth: 1, borderRadius: [4, 4, 0, 0] },
        },
      ],
    },
  };
}

function pieChart(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors): BuiltChart {
  const rows = result.rows.filter((row) => row[1] !== null && Number(row[1]) > 0);
  return {
    keys: { x: rows.map((row) => row[0]), colors: [] },
    option: {
      tooltip: { trigger: "item", valueFormatter: (value) => formatValue(value as number, config) },
      legend: { type: "scroll", bottom: 0 },
      series: [
        {
          type: "pie",
          name: MEASURE_LABELS[config.y.measure],
          radius: config.chart === "donut" ? ["45%", "70%"] : "70%",
          center: ["50%", "45%"],
          avoidLabelOverlap: true,
          label: { formatter: "{d}%" },
          itemStyle: { borderColor: INK, borderWidth: 1.5 },
          data: rows.map((row, position) => ({
            name: formatLabel(row[0], config.x?.field),
            value: Number(row[1]),
            itemStyle: { color: resolveColor(row[0], position, config.x?.field, config, categoryColors) },
          })),
        },
      ],
    },
  };
}

// bar / line / area, with or without a colour split.
function cartesianChart(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors): BuiltChart {
  const split = result.columns.includes("color");
  const xKeys = unique(result.rows.map((row) => row[0]));
  const colorKeys = split ? unique(result.rows.map((row) => row[1])) : [null];
  const valueIndex = split ? 2 : 1;

  // (x, colour) -> value, then one series per colour lined up with xKeys.
  const lookup = new Map(result.rows.map((row) => [`${row[0]}|${split ? row[1] : ""}`, row[valueIndex]]));
  const horizontal = config.chart === "bar" && config.orientation === "horizontal";
  const seriesType = config.chart === "bar" ? "bar" : "line";
  const manyPoints = xKeys.length > 40;
  // A bar chart by category/merchant/... with no split: every bar is its own entity, so each
  // gets its own colour (a category's colour is the bar's default).
  const perBar = seriesType === "bar" && !split && config.x?.field !== "date";
  // Rounded data-ends only on bars that aren't stacked (a stack's inner ends must stay flat).
  const stackedBars = split && config.stacked;
  const radius = stackedBars ? 0 : 4;

  const series = colorKeys.map((colorKey, position) => {
    const data = xKeys.map((x) => toNumber(lookup.get(`${x}|${split ? colorKey : ""}`) ?? null));
    const name = split ? formatLabel(colorKey, config.color?.field) : MEASURE_LABELS[config.y.measure];
    const stack = split && (config.stacked || config.chart === "area") ? "total" : undefined;
    const color = resolveColor(split ? colorKey : SINGLE_SERIES_KEY, position, split ? config.color?.field : undefined, config, categoryColors);

    if (seriesType === "bar") {
      const barStyle = {
        color,
        borderColor: INK,
        borderWidth: 1,
        borderRadius: horizontal ? [0, radius, radius, 0] : [radius, radius, 0, 0],
      };
      return {
        type: "bar" as const,
        name,
        stack,
        emphasis: { focus: "series" as const },
        itemStyle: barStyle,
        data: perBar
          ? data.map((value, index) => ({
              value,
              itemStyle: { ...barStyle, color: resolveColor(xKeys[index], index, config.x?.field, config, categoryColors) },
            }))
          : data,
      };
    }
    return {
      type: "line" as const,
      name,
      data,
      stack,
      showSymbol: !manyPoints,
      symbolSize: 8,
      lineStyle: { width: 2.5, color },
      itemStyle: { color, borderColor: "#ffffff", borderWidth: 2 },
      areaStyle: config.chart === "area" ? { opacity: 0.28, color } : undefined,
      emphasis: { focus: "series" as const },
    };
  });

  const categoryAxis = {
    type: "category" as const,
    data: xKeys.map((x) => formatLabel(x, config.x?.field, config.x?.granularity)),
    inverse: horizontal, // horizontal bars read top-down, biggest first
    boundaryGap: seriesType === "bar",
  };
  const valueAxis = { type: "value" as const, axisLabel: { formatter: axisFormatter(config) } };

  return {
    keys: { x: xKeys, colors: split ? colorKeys : [] },
    option: {
      grid: { left: 8, right: 16, top: split ? 36 : 16, bottom: 8 },
      legend: split ? { type: "scroll", top: 0 } : undefined,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: seriesType === "bar" ? "shadow" : "line" },
        valueFormatter: (value) => formatValue(value as number | null, config),
      },
      xAxis: horizontal ? valueAxis : categoryAxis,
      yAxis: horizontal ? categoryAxis : valueAxis,
      series,
    },
  };
}

export function toOption(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors = new Map()): BuiltChart {
  if (config.chart === "histogram") return histogramChart(config, result, categoryColors);
  if (config.chart === "pie" || config.chart === "donut") return pieChart(config, result, categoryColors);
  return cartesianChart(config, result, categoryColors);
}
