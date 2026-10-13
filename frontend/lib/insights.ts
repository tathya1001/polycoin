// Plain logic for the dashboard page: API paths, labels, formatting, the editor's spec
// building and chart click-through. No React, so it stays easy to read and to test.

import type {
  Agg,
  Catalogue,
  Category,
  Cell,
  ChartType,
  DatePreset,
  Dimension,
  Granularity,
  Measure,
  PanelConfig,
  PanelFilters,
  QueryOutcome,
  QueryResult,
} from "@/lib/types";

export const FIELDS_URL = "/api/insights/fields/";
export const QUERY_URL = "/api/insights/query/";
export const DASHBOARDS_URL = "/api/dashboards/";

export const dashboardUrl = (id: string) => `${DASHBOARDS_URL}${id}/`;
export const panelsUrl = (id: string) => `${DASHBOARDS_URL}${id}/panels/`;
export const panelUrl = (id: string, panelId: string) => `${DASHBOARDS_URL}${id}/panels/${panelId}/`;
export const layoutUrl = (id: string) => `${DASHBOARDS_URL}${id}/layout/`;

export function isError(outcome: QueryOutcome | undefined): outcome is { error: { code: string; detail: string } } {
  return !!outcome && "error" in outcome;
}

// --- labels -------------------------------------------------------------------

export const CHART_LABELS: Record<ChartType, string> = {
  kpi: "Number",
  bar: "Bar",
  line: "Line",
  area: "Area",
  pie: "Pie",
  donut: "Donut",
  histogram: "Histogram",
};

export const CHART_ICONS: Record<ChartType, string> = {
  kpi: "123",
  bar: "▮▮",
  line: "╱╲",
  area: "◢◣",
  pie: "◔",
  donut: "◯",
  histogram: "▁▃▇",
};

export const DIMENSION_LABELS: Record<Dimension, string> = {
  date: "Date",
  weekday: "Day of week",
  month_of_year: "Month of year",
  category: "Category",
  txn_type: "Money in / out",
  merchant: "Merchant",
};

export const MEASURE_LABELS: Record<Measure, string> = {
  spend: "Spend",
  income: "Income",
  net: "Net (income − spend)",
  amount: "Amount (in and out)",
  count: "Number of transactions",
  balance: "Balance",
};

export const AGG_LABELS: Record<Agg, string> = {
  sum: "Total",
  avg: "Average",
  min: "Smallest",
  max: "Largest",
  median: "Median",
  count: "Count",
  last: "Last (end of period)",
};

export const GRANULARITY_LABELS: Record<Granularity, string> = {
  day: "Day",
  week: "Week",
  month: "Month",
  quarter: "Quarter",
  year: "Year",
};

export const PRESET_LABELS: Record<DatePreset | "inherit", string> = {
  inherit: "Same as dashboard",
  this_month: "This month",
  last_month: "Last month",
  last_3_months: "Last 3 months",
  last_12_months: "Last 12 months",
  this_year: "This year",
  all: "All time",
  custom: "Custom range",
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // the backend's 0 = Monday
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// --- dates (always "YYYY-MM-DD", read as UTC so time zones can't shift a day) --------

function parseDay(text: string): Date {
  return new Date(`${text}T00:00:00Z`);
}

function formatDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addDays(text: string, days: number): string {
  const date = parseDay(text);
  date.setUTCDate(date.getUTCDate() + days);
  return formatDay(date);
}

function addMonths(text: string, months: number): string {
  const date = parseDay(text);
  date.setUTCMonth(date.getUTCMonth() + months); // bucket starts are day 1, so no overflow
  return formatDay(date);
}

// Today in the browser's own time zone (toISOString would give the UTC date, which is a
// different day for the first hours after midnight in India).
export function todayLocal(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// The last day of the time bucket that starts on `start`.
function bucketEnd(start: string, granularity: Granularity): string {
  const next = {
    day: () => addDays(start, 1),
    week: () => addDays(start, 7),
    month: () => addMonths(start, 1),
    quarter: () => addMonths(start, 3),
    year: () => addMonths(start, 12),
  }[granularity]();
  return addDays(next, -1);
}

// --- formatting -----------------------------------------------------------------

// Money arrives as a decimal string ("1234.50"). Number() is only for display.
export function money(value: Cell): string {
  if (value === null || value === "") return "–";
  return `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function isCountLike(config: Pick<PanelConfig, "y">): boolean {
  return config.y.measure === "count" || config.y.agg === "count";
}

export function formatValue(value: Cell, config: Pick<PanelConfig, "y">): string {
  if (value === null) return "–";
  return isCountLike(config) ? Number(value).toLocaleString("en-IN") : money(value);
}

// How an x (or colour) value reads on an axis, legend or tooltip.
export function formatLabel(value: Cell, field: Dimension | undefined, granularity?: Granularity): string {
  if (value === null) return "–";
  if (field === "weekday") return WEEKDAYS[Number(value)] ?? String(value);
  if (field === "month_of_year") return MONTHS[Number(value) - 1] ?? String(value);
  if (field === "txn_type") return value === "credit" ? "Money in" : value === "debit" ? "Money out" : String(value);
  if (field === "date" && typeof value === "string") {
    const date = parseDay(value);
    const month = MONTHS[date.getUTCMonth()];
    const year = date.getUTCFullYear();
    if (granularity === "year") return String(year);
    if (granularity === "quarter") return `Q${Math.floor(date.getUTCMonth() / 3) + 1} ${year}`;
    if (granularity === "month") return `${month} ${year}`;
    if (granularity === "week") return `w/c ${date.getUTCDate()} ${month}`;
    return `${date.getUTCDate()} ${month}`;
  }
  return String(value);
}

// --- building specs in the editor --------------------------------------------------

export const EMPTY_FILTERS: PanelFilters = {
  date: { preset: "inherit" },
  type: null,
  categories: [],
  merchant_contains: "",
};

export const DEFAULT_DASHBOARD_FILTERS: PanelFilters = {
  ...EMPTY_FILTERS,
  date: { preset: "last_3_months" },
};

// A sensible starting point for each chart type, used by "Add panel" and the type picker.
export function defaultConfig(chart: ChartType): PanelConfig {
  const base: PanelConfig = {
    v: 1,
    chart,
    y: { measure: "spend", agg: "sum" },
    sort: "measure_desc",
    limit: 10,
    bins: 20,
    compare: false,
    stacked: false,
    orientation: "vertical",
    filters: EMPTY_FILTERS,
  };
  if (chart === "kpi") return { ...base, compare: true };
  if (chart === "line" || chart === "area") return { ...base, x: { field: "date", granularity: "month" } };
  if (chart === "histogram") return base;
  return { ...base, x: { field: "category" } };
}

// Pie, donut and histogram reject some measures. The catalogue doesn't list these yet, so
// they are mirrored here from spec.validate_encoding.
export function measuresFor(chart: ChartType, catalogue: Catalogue): Catalogue["measures"] {
  return catalogue.measures.filter((m) => {
    if (chart === "pie" || chart === "donut") return m.id !== "net" && m.id !== "balance";
    if (chart === "histogram") return m.id !== "count";
    return true;
  });
}

// Make a draft obey the chart rules after any change (a new chart type, a new x field...),
// so the editor never sends a combination the backend is certain to reject.
export function normalizeConfig(config: PanelConfig, catalogue: Catalogue): PanelConfig {
  const rules = catalogue.charts[config.chart];
  const next: PanelConfig = { ...config, y: { ...config.y } };

  if (rules.x.length === 0) {
    delete next.x;
  } else {
    const field = config.x && rules.x.includes(config.x.field) ? config.x.field : rules.x[0];
    next.x = field === "date" ? { field, granularity: config.x?.granularity ?? "month" } : { field };
  }

  const measures = measuresFor(config.chart, catalogue);
  const measure = measures.find((m) => m.id === config.y.measure) ?? measures[0];
  next.y = {
    measure: measure.id,
    agg: measure.aggs.includes(config.y.agg) ? config.y.agg : measure.default_agg,
  };

  if (!rules.color || !config.color || config.color.field === next.x?.field || config.color.field === "date") {
    delete next.color;
  }
  if (config.chart !== "kpi") next.compare = false;
  if (!next.color) next.stacked = false;
  return next;
}

// --- clicking a chart: open the matching transactions ------------------------------

export function hasCategoricalX(config: PanelConfig): boolean {
  return !!config.x && config.x.field !== "date";
}

// The /transactions link for a clicked bar / slice / point, or null if a click can't be
// expressed as transaction filters. `filters` are the panel's effective filters.
export function drillDownUrl(
  config: PanelConfig,
  result: QueryResult,
  filters: PanelFilters,
  picked: { x: Cell; color?: Cell },
  categories: Category[],
): string | null {
  let from = result.period.from;
  let to = result.period.to;
  let type = filters.type;
  let category = filters.categories.length === 1 ? filters.categories[0] : null;

  const apply = (field: Dimension | undefined, value: Cell, granularity?: Granularity) => {
    if (value === null || field === undefined) return;
    if (field === "category") {
      const match = categories.find((c) => c.name.toLowerCase() === String(value).toLowerCase());
      if (match) category = match.id; // "Other" (the folded rest) has no single category
    } else if (field === "txn_type" && (value === "credit" || value === "debit")) {
      type = value;
    } else if (field === "date" && granularity && typeof value === "string") {
      if (value > from) from = value;
      const end = bucketEnd(value, granularity);
      if (end < to) to = end;
    }
  };
  apply(config.x?.field, picked.x, config.x?.granularity);
  apply(config.color?.field, picked.color ?? null);

  const params = new URLSearchParams({ from, to });
  if (type) params.set("type", type);
  if (category) params.set("category", category);
  return `/transactions?${params}`;
}

// A panel's own filters win; empty ones fall back to the dashboard's (as on the backend).
export function effectiveFilters(panel: PanelFilters, dashboard: PanelFilters): PanelFilters {
  return {
    date: panel.date.preset === "inherit" ? dashboard.date : panel.date,
    type: panel.type ?? dashboard.type,
    categories: panel.categories.length ? panel.categories : dashboard.categories,
    merchant_contains: panel.merchant_contains || dashboard.merchant_contains,
  };
}
