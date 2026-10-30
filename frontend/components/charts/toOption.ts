// Turns a panel config plus its query result into an ECharts option. Pure: no React, no DOM.
//
// The backend returns "long" rows, one per (x, colour) pair:  [x, value] or [x, colour, value].
// ECharts wants "wide" series, one per colour, each lined up with the x axis, so this pivots.
//
// Text from the user's data (category and merchant names) is only ever passed as plain
// strings. Tooltips use ECharts' default markup, which escapes it; there is deliberately no
// custom HTML formatter anywhere here.

import type { ComposeOption } from "echarts/core";
import type { BarSeriesOption, HeatmapSeriesOption, LineSeriesOption, PieSeriesOption } from "echarts/charts";
import type {
  CalendarComponentOption,
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
  VisualMapComponentOption,
} from "echarts/components";
import { FALLBACK_SERIES_COLORS } from "@/lib/colors";
import { CHART_LOOKS, type ChartLook } from "@/lib/theme";
import {
  MEASURE_LABELS,
  defaultFormat,
  formatLabel,
  formatValue,
  isPercent,
  isPlainNumber,
  sourceColorKey,
} from "@/lib/insights";
import type { Cell, Dimension, PanelConfig, QueryResult } from "@/lib/types";

export type ChartOption = ComposeOption<
  | BarSeriesOption
  | HeatmapSeriesOption
  | LineSeriesOption
  | PieSeriesOption
  | CalendarComponentOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
  | VisualMapComponentOption
>;

// What a click on (seriesIndex, dataIndex) refers to, in the backend's raw values. Marks that
// sit on two axes (a calendar day, a heatmap cell) are listed in `cells`, by data index.
export type ChartKeys = { x: Cell[]; colors: Cell[]; cells?: { x: Cell; row?: Cell }[] };

// The x value a chart dims everything else against, because it was picked to filter the
// other panels. Charts that draw one mark per x value (bars, slices) honour it.
export type Highlight = Cell | undefined;

const DIMMED = 0.3;
const dimmed = (x: Cell, highlight: Highlight) => (highlight !== undefined && x !== highlight ? DIMMED : 1);

export type BuiltChart = { option: ChartOption; keys: ChartKeys | null };

// Category name (lower case) -> "#RRGGBB". Category values in a result are names.
export type CategoryColors = ReadonlyMap<string, string>;

// The key under which a chart with a single series stores its colour in series_colors.
export const SINGLE_SERIES_KEY = "_";


const toNumber = (value: Cell) => (value === null ? null : Number(value));

const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

const formatOf = (config: PanelConfig) => config.format ?? defaultFormat();

// Axis numbers: short by default (₹1.2L), or written out in full when the panel asks for it.
function axisFormatter(config: PanelConfig) {
  const full = formatOf(config).number === "full";
  const write = (value: number) => (full ? value.toLocaleString("en-IN") : compact.format(value));
  return (value: number) => {
    if (isPercent(config)) return `${write(value)}%`;
    return isPlainNumber(config) ? write(value) : `₹${write(value)}`;
  };
}

// A value as written on a label or in a tooltip: in full unless the panel asks for short numbers.
function valueText(config: PanelConfig, value: number | null): string {
  if (value === null || formatOf(config).number !== "compact") return formatValue(value, config);
  if (isPercent(config)) return `${compact.format(value)}%`;
  return isPlainNumber(config) ? compact.format(value) : `₹${compact.format(value)}`;
}

type LegendPosition = "top" | "bottom" | "right";

// Where the legend goes, or null for none. "auto" keeps each chart's own default: shown when
// there is more than one thing to tell apart.
export function legendPosition(config: PanelConfig, wanted: boolean, fallback: "top" | "bottom"): LegendPosition | null {
  const choice = formatOf(config).legend;
  if (choice === "none") return null;
  if (choice === "auto") return wanted ? fallback : null;
  return choice;
}

function legendOption(position: LegendPosition | null): LegendComponentOption | undefined {
  if (position === null) return undefined;
  if (position === "right") return { type: "scroll", orient: "vertical", right: 0, top: "middle" };
  return position === "top" ? { type: "scroll", top: 0 } : { type: "scroll", bottom: 0 };
}

// Value labels written on the marks, when the panel asks for them.
function labelOption(config: PanelConfig, position: "top" | "right" | "inside") {
  return formatOf(config).labels
    ? {
        show: true,
        position,
        formatter: (params: { value?: unknown }) => valueText(config, toNumber(params.value as Cell)),
      }
    : undefined;
}

function unique(values: Cell[]): Cell[] {
  return [...new Set(values)];
}

// The colour of one series / bar / slice. Most specific wins:
//   1. the panel's own override       (series_colors[key])
//   2. the category's or data source's colour (when the thing being coloured IS one)
//   3. the default sequence, by position
// `key` is the raw value (a category name, "credit", a month...), or SINGLE_SERIES_KEY.
export function resolveColor(
  key: Cell | typeof SINGLE_SERIES_KEY,
  position: number,
  field: Dimension | undefined,
  config: Pick<PanelConfig, "series_colors">,
  categoryColors: CategoryColors,
  look: ChartLook = CHART_LOOKS.classic,
): string {
  const text = String(key);
  const override = config.series_colors?.[text];
  if (override) return look.series(override);
  if (field === "category" && key !== null) {
    const own = categoryColors.get(text.toLowerCase());
    if (own) return look.series(own);
  }
  if (field === "data_source" && key !== null) {
    const own = categoryColors.get(sourceColorKey(text));
    if (own) return look.series(own);
  }
  return look.series(FALLBACK_SERIES_COLORS[position % FALLBACK_SERIES_COLORS.length]);
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

export function seriesSwatches(
  config: PanelConfig,
  result: QueryResult,
  categoryColors: CategoryColors,
  look: ChartLook = CHART_LOOKS.classic,
): SeriesSwatch[] {
  if (config.chart === "kpi" || config.chart === "calendar" || config.chart === "heatmap") return []; // one colour scale
  if (config.chart === "histogram") {
    return [{ key: SINGLE_SERIES_KEY, label: MEASURE_LABELS[config.y.measure], color: resolveColor(SINGLE_SERIES_KEY, 0, undefined, config, categoryColors, look) }];
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
        color: resolveColor(SINGLE_SERIES_KEY, 0, undefined, config, categoryColors, look),
      },
    ];
  }
  return keys.map((key, position) => ({
    key: String(key),
    label: formatLabel(key, field),
    color: resolveColor(key, position, field, config, categoryColors, look),
  }));
}

function histogramChart(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors, look: ChartLook): BuiltChart {
  const labels = result.rows.map(([start, end]) => `${compact.format(Number(start))}–${compact.format(Number(end))}`);
  const color = resolveColor(SINGLE_SERIES_KEY, 0, undefined, config, categoryColors, look);
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
          label: formatOf(config).labels ? { show: true, position: "top" as const } : undefined,
          itemStyle: { color, borderColor: look.barEdge.color, borderWidth: look.barEdge.width, borderRadius: [4, 4, 0, 0] },
        },
      ],
    },
  };
}

const pieLabelStyle = (look: ChartLook) => ({ color: look.text, textBorderColor: "transparent", textBorderWidth: 0 });

function pieChart(config: PanelConfig, result: QueryResult, categoryColors: CategoryColors, highlight: Highlight, look: ChartLook): BuiltChart {
  const rows = result.rows.filter((row) => row[1] !== null && Number(row[1]) > 0);
  const legend = legendPosition(config, true, "bottom");
  return {
    keys: { x: rows.map((row) => row[0]), colors: [] },
    option: {
      tooltip: { trigger: "item", valueFormatter: (value) => valueText(config, value as number) },
      legend: legendOption(legend),
      series: [
        {
          type: "pie",
          name: MEASURE_LABELS[config.y.measure],
          radius: config.chart === "donut" ? ["45%", "70%"] : "70%",
          center: [legend === "right" ? "40%" : "50%", legend === "top" ? "55%" : legend === "bottom" ? "45%" : "50%"],
          avoidLabelOverlap: true,
          // Share by default; with labels on, the value as well. ECharts colours outside labels
          // itself (dark grey in a white halo), which smears on a dark surface: use the mode's text.
          label: formatOf(config).labels
            ? {
                ...pieLabelStyle(look),
                formatter: (params: { value?: unknown; percent?: number }) =>
                  `${valueText(config, Number(params.value))} (${Math.round((params.percent ?? 0) * 10) / 10}%)`,
              }
            : { ...pieLabelStyle(look), formatter: "{d}%" },
          itemStyle: { borderColor: look.sliceEdge.color, borderWidth: look.sliceEdge.width },
          data: rows.map((row, position) => ({
            name: formatLabel(row[0], config.x?.field),
            value: Number(row[1]),
            itemStyle: {
              color: resolveColor(row[0], position, config.x?.field, config, categoryColors, look),
              opacity: dimmed(row[0], highlight),
            },
          })),
        },
      ],
    },
  };
}

// bar / line / area, with or without a colour split.
function cartesianChart(
  config: PanelConfig,
  result: QueryResult,
  categoryColors: CategoryColors,
  highlight: Highlight,
  look: ChartLook,
): BuiltChart {
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
  const legend = legendPosition(config, split, "top");

  const series = colorKeys.map((colorKey, position) => {
    const data = xKeys.map((x) => toNumber(lookup.get(`${x}|${split ? colorKey : ""}`) ?? null));
    const name = split ? formatLabel(colorKey, config.color?.field) : MEASURE_LABELS[config.y.measure];
    const stack = split && (config.stacked || config.chart === "area") ? "total" : undefined;
    const color = resolveColor(split ? colorKey : SINGLE_SERIES_KEY, position, split ? config.color?.field : undefined, config, categoryColors, look);

    if (seriesType === "bar") {
      const barStyle = {
        color,
        borderColor: look.barEdge.color,
        borderWidth: look.barEdge.width,
        borderRadius: horizontal ? [0, radius, radius, 0] : [radius, radius, 0, 0],
      };
      return {
        type: "bar" as const,
        name,
        stack,
        emphasis: { focus: "series" as const },
        label: labelOption(config, stackedBars ? "inside" : horizontal ? "right" : "top"),
        itemStyle: barStyle,
        data:
          perBar || highlight !== undefined
            ? data.map((value, index) => ({
                value,
                itemStyle: {
                  ...barStyle,
                  color: perBar ? resolveColor(xKeys[index], index, config.x?.field, config, categoryColors, look) : color,
                  opacity: dimmed(xKeys[index], highlight),
                },
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
      label: labelOption(config, "top"),
      lineStyle: { width: 2.5, color },
      itemStyle: { color, borderColor: look.surface, borderWidth: 2 },
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
  const { min, max } = formatOf(config).axis;
  const valueAxis = {
    type: "value" as const,
    axisLabel: { formatter: axisFormatter(config) },
    ...(min !== null ? { min } : {}),
    ...(max !== null ? { max } : {}),
  };

  return {
    keys: { x: xKeys, colors: split ? colorKeys : [] },
    option: {
      grid: {
        left: 8,
        right: legend === "right" ? 120 : 16,
        top: legend === "top" ? 36 : 16,
        bottom: legend === "bottom" ? 36 : 8,
      },
      legend: legendOption(legend),
      tooltip: {
        trigger: "axis",
        axisPointer: { type: seriesType === "bar" ? "shadow" : "line" },
        valueFormatter: (value) => valueText(config, value as number | null),
      },
      xAxis: horizontal ? valueAxis : categoryAxis,
      yAxis: horizontal ? categoryAxis : valueAxis,
      series,
    },
  };
}

// --- heatmaps ---------------------------------------------------------------------------------


// A tooltip body is HTML in ECharts. The other charts use its default markup, which escapes
// user text; a heatmap's default is not what we want to show, so this writes the one line itself
// and escapes every piece of it.
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => (({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }) as Record<string, string>)[char]);
}

const tooltipLine = (name: string, value: string) => `${escapeHtml(name)}: <b>${escapeHtml(value)}</b>`;

// The colour scale legend: one hue from small to large, or orange to blue around zero when
// the measure goes negative (net).
function colourScale(values: number[], config: PanelConfig, look: ChartLook): VisualMapComponentOption {
  const low = values.length ? Math.min(...values) : 0;
  const high = values.length ? Math.max(...values) : 1;
  const diverging = low < 0;
  const reach = Math.max(Math.abs(low), Math.abs(high)) || 1;
  const write = axisFormatter(config);
  return {
    type: "continuous",
    min: diverging ? -reach : low,
    max: diverging ? reach : high === low ? low + 1 : high,
    calculable: false,
    orient: "horizontal",
    left: "center",
    bottom: 0,
    itemWidth: 12,
    itemHeight: 120,
    formatter: (value) => write(Number(value)),
    inRange: { color: diverging ? look.diverging : look.sequential },
  };
}

// A 2px gap the colour of the surface between neighbouring cells.
const cellStyle = (look: ChartLook) => ({ borderColor: look.surface, borderWidth: 2, borderRadius: 3 });

function calendarChart(config: PanelConfig, result: QueryResult, look: ChartLook): BuiltChart {
  const data: [string, number][] = result.rows.map((row) => [String(row[0]), Number(row[1])]);
  return {
    keys: { x: [], colors: [], cells: data.map(([day]) => ({ x: day })) },
    option: {
      tooltip: {
        trigger: "item",
        formatter: (params) => {
          const [day, value] = (params as unknown as { value: [string, number] }).value;
          return tooltipLine(formatLabel(day, "date", "day"), valueText(config, value));
        },
      },
      visualMap: colourScale(data.map(([, value]) => value), config, look),
      calendar: {
        range: [result.period.from, result.period.to],
        top: 26,
        left: 34,
        right: 12,
        bottom: 44,
        cellSize: ["auto", "auto"],
        yearLabel: { show: false },
        dayLabel: { firstDay: 1, nameMap: "en" },
        monthLabel: { nameMap: "en" },
        splitLine: { show: true, lineStyle: { color: look.calendarLine, width: 1 } },
        itemStyle: { color: look.emptyCell, borderColor: look.surface, borderWidth: 2 },
      },
      series: [
        {
          type: "heatmap",
          coordinateSystem: "calendar",
          data,
          itemStyle: cellStyle(look),
          label: formatOf(config).labels
            ? { show: true, formatter: (params) => valueText(config, (params.value as [string, number])[1]) }
            : undefined,
        },
      ],
    },
  };
}

function matrixChart(config: PanelConfig, result: QueryResult, look: ChartLook): BuiltChart {
  const xKeys = result.axes?.x ?? [];
  const rowKeys = result.axes?.rows ?? [];
  const xIndex = new Map(xKeys.map((key, index) => [key, index]));
  const rowIndex = new Map(rowKeys.map((key, index) => [key, index]));
  const data: [number, number, number][] = [];
  const cells: { x: Cell; row: Cell }[] = []; // the raw keys of each data point, for clicks
  for (const row of result.rows) {
    const x = xIndex.get(row[0]);
    const y = rowIndex.get(row[1]);
    if (x === undefined || y === undefined) continue;
    data.push([x, y, Number(row[2])]);
    cells.push({ x: row[0], row: row[1] });
  }
  const xLabel = (index: number) => formatLabel(xKeys[index], config.x?.field, config.x?.granularity);
  const rowLabel = (index: number) => formatLabel(rowKeys[index], config.rows?.field);

  return {
    keys: { x: [], colors: [], cells },
    option: {
      grid: { left: 8, right: 16, top: 8, bottom: 56 },
      tooltip: {
        trigger: "item",
        formatter: (params) => {
          const [x, y, value] = (params as unknown as { value: [number, number, number] }).value;
          return tooltipLine(`${xLabel(x)} · ${rowLabel(y)}`, valueText(config, value));
        },
      },
      xAxis: {
        type: "category",
        data: xKeys.map((_, index) => xLabel(index)),
        splitArea: { show: true },
        axisLabel: { interval: 0, hideOverlap: true },
      },
      yAxis: { type: "category", data: rowKeys.map((_, index) => rowLabel(index)), inverse: true, splitArea: { show: true } },
      visualMap: colourScale(data.map(([, , value]) => value), config, look),
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: cellStyle(look),
          label: formatOf(config).labels
            ? { show: true, formatter: (params) => valueText(config, (params.value as [number, number, number])[2]) }
            : undefined,
        },
      ],
    },
  };
}

export function toOption(
  config: PanelConfig,
  result: QueryResult,
  categoryColors: CategoryColors = new Map(),
  highlight?: Highlight,
  look: ChartLook = CHART_LOOKS.classic,
): BuiltChart {
  if (config.chart === "calendar") return calendarChart(config, result, look);
  if (config.chart === "heatmap") return matrixChart(config, result, look);
  if (config.chart === "histogram") return histogramChart(config, result, categoryColors, look);
  if (config.chart === "pie" || config.chart === "donut") return pieChart(config, result, categoryColors, highlight, look);
  return cartesianChart(config, result, categoryColors, highlight, look);
}
