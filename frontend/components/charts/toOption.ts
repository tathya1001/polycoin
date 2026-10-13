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
import { MEASURE_LABELS, formatLabel, formatValue, isCountLike } from "@/lib/insights";
import type { Cell, PanelConfig, QueryResult } from "@/lib/types";

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

const toNumber = (value: Cell) => (value === null ? null : Number(value));

const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

function axisFormatter(config: PanelConfig) {
  return (value: number) => (isCountLike(config) ? compact.format(value) : `₹${compact.format(value)}`);
}

function unique(values: Cell[]): Cell[] {
  return [...new Set(values)];
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

function histogramChart(config: PanelConfig, result: QueryResult): BuiltChart {
  const labels = result.rows.map(([start, end]) => `${compact.format(Number(start))}–${compact.format(Number(end))}`);
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
        },
      ],
    },
  };
}

function pieChart(config: PanelConfig, result: QueryResult): BuiltChart {
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
          data: rows.map((row) => ({
            name: formatLabel(row[0], config.x?.field),
            value: Number(row[1]),
          })),
        },
      ],
    },
  };
}

// bar / line / area, with or without a colour split.
function cartesianChart(config: PanelConfig, result: QueryResult): BuiltChart {
  const split = result.columns.includes("color");
  const xKeys = unique(result.rows.map((row) => row[0]));
  const colorKeys = split ? unique(result.rows.map((row) => row[1])) : [null];
  const valueIndex = split ? 2 : 1;

  // (x, colour) -> value, then one series per colour lined up with xKeys.
  const lookup = new Map(result.rows.map((row) => [`${row[0]}|${split ? row[1] : ""}`, row[valueIndex]]));
  const horizontal = config.chart === "bar" && config.orientation === "horizontal";
  const seriesType = config.chart === "bar" ? "bar" : "line";
  const manyPoints = xKeys.length > 40;

  const series = colorKeys.map((colorKey) => {
    const data = xKeys.map((x) => toNumber(lookup.get(`${x}|${split ? colorKey : ""}`) ?? null));
    const name = split ? formatLabel(colorKey, config.color?.field) : MEASURE_LABELS[config.y.measure];
    const stack = split && (config.stacked || config.chart === "area") ? "total" : undefined;
    if (seriesType === "bar") {
      return { type: "bar" as const, name, data, stack, emphasis: { focus: "series" as const } };
    }
    return {
      type: "line" as const,
      name,
      data,
      stack,
      showSymbol: !manyPoints,
      areaStyle: config.chart === "area" ? { opacity: 0.25 } : undefined,
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

export function toOption(config: PanelConfig, result: QueryResult): BuiltChart {
  if (config.chart === "histogram") return histogramChart(config, result);
  if (config.chart === "pie" || config.chart === "donut") return pieChart(config, result);
  return cartesianChart(config, result);
}
