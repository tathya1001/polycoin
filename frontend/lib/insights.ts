// Plain logic for the dashboard page: API paths, labels, formatting, the editor's spec
// building and chart click-through. No React, so it stays easy to read and to test.

import { money } from "@/lib/format";
import { isText } from "@/lib/types";
import type {
  DataSource,
  Agg,
  AnyPanelConfig,
  BindField,
  Bindings,
  CalcType,
  Catalogue,
  Category,
  Cell,
  ChartType,
  DataChartType,
  DatePreset,
  Dimension,
  FormatOptions,
  Formula,
  FormulaForm,
  FormulaFunctionGroup,
  Granularity,
  KpiCompare,
  KpiDirection,
  KpiFigure,
  KpiOptions,
  LegendPosition,
  Measure,
  NumberFormat,
  PanelConfig,
  PanelFilters,
  Picked,
  DashboardParameters,
  ParameterName,
  QueryOutcome,
  QueryResult,
  TableCalc,
} from "@/lib/types";

export const FIELDS_URL = "/api/insights/fields/";
export const QUERY_URL = "/api/insights/query/";
export const ROWS_URL = "/api/insights/rows/";
export const DASHBOARDS_URL = "/api/dashboards/";

export const dashboardUrl = (id: string) => `${DASHBOARDS_URL}${id}/`;
export const panelsUrl = (id: string) => `${DASHBOARDS_URL}${id}/panels/`;
export const panelUrl = (id: string, panelId: string) => `${DASHBOARDS_URL}${id}/panels/${panelId}/`;
export const layoutUrl = (id: string) => `${DASHBOARDS_URL}${id}/layout/`;
export const settingsUrl = (id: string) => `${DASHBOARDS_URL}${id}/settings/`;

export function isError(outcome: QueryOutcome | undefined): outcome is { error: { code: string; detail: string } } {
  return !!outcome && "error" in outcome;
}

// --- labels -------------------------------------------------------------------

export const NUMBER_FORMAT_LABELS: Record<NumberFormat, string> = {
  auto: "Automatic (short on axes, full in tooltips)",
  full: "Full numbers (₹1,23,456)",
  compact: "Short numbers (₹1.2L)",
};

export const LEGEND_LABELS: Record<LegendPosition, string> = {
  auto: "Automatic",
  top: "Top",
  bottom: "Bottom",
  right: "Right",
  none: "Hidden",
};

export const CHART_LABELS: Record<ChartType, string> = {
  kpi: "Number",
  bar: "Bar",
  line: "Line",
  area: "Area",
  pie: "Pie",
  donut: "Donut",
  histogram: "Histogram",
  calendar: "Calendar",
  heatmap: "Heatmap",
  text: "Text note",
};

export const DIMENSION_LABELS: Record<Dimension, string> = {
  date: "Date",
  weekday: "Day of week",
  month_of_year: "Month of year",
  category: "Category",
  txn_type: "Money in / out",
  merchant: "Merchant",
  data_source: "Data source",
};

export const MEASURE_LABELS: Record<Measure, string> = {
  spend: "Spend",
  income: "Income",
  net: "Net (income − spend)",
  amount: "Amount (in and out)",
  count: "Number of transactions",
  balance: "Balance",
  formula: "Calculated field",
};

export const FORMULA_FORM_LABELS: Record<FormulaForm, string> = {
  number: "Number",
  percent: "Percentage",
  money: "Money (₹)",
};

// What a new calculated field starts as: the share of income that was not spent.
export const DEFAULT_FORMULA: Formula = { expression: "(income - spend) / income * 100", as: "percent" };

// Ready-made formulas the editor offers, to show what the language can say.
export const FORMULA_EXAMPLES: { label: string; formula: Formula }[] = [
  { label: "Savings rate", formula: DEFAULT_FORMULA },
  {
    label: "Grocery share",
    formula: { expression: 'SUM(IF [Category] = "Groceries" THEN [Spend] END) / spend * 100', as: "percent" },
  },
  { label: "Daily spend", formula: { expression: "spend / days", as: "money" } },
  {
    label: "Weekend share",
    formula: { expression: "SUM(IF WEEKDAY([Date]) >= 6 THEN [Spend] END) / spend * 100", as: "percent" },
  },
  { label: "Merchants", formula: { expression: "COUNTD([Merchant])", as: "number" } },
];

export const FORMULA_GROUP_LABELS: Record<FormulaFunctionGroup, string> = {
  aggregate: "Aggregations",
  logic: "Logic and missing values",
  number: "Numbers",
  text: "Text",
  date: "Dates",
};

// Put `before` and `after` around the selection [start, end) of `text`. With nothing selected
// the cursor lands between them (inside the brackets of "SUM(" + ")"); with a selection it
// lands after both, so selecting [Spend] and picking SUM gives "SUM([Spend])".
export function insertAt(
  text: string,
  start: number,
  end: number,
  before: string,
  after = "",
): { text: string; cursor: number } {
  const selected = text.slice(start, end);
  return {
    text: text.slice(0, start) + before + selected + after + text.slice(end),
    cursor: start + before.length + selected.length + (selected ? after.length : 0),
  };
}

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

export const CALC_LABELS: Record<CalcType, string> = {
  running_total: "Running total",
  percent_of_total: "% of total",
  moving_average: "Moving average",
  change: "Change",
};

export const KPI_COMPARE_LABELS: Record<KpiCompare, string> = {
  none: "Nothing",
  previous: "The previous period",
  year_ago: "The same period a year ago",
  average: "The average of earlier periods",
};

export const KPI_DIRECTION_LABELS: Record<KpiDirection, string> = {
  auto: "Decided by the measure (less spend is good)",
  up_is_good: "Good news",
  down_is_good: "Bad news",
};

export const KPI_FIGURE_LABELS: Record<KpiFigure, string> = {
  count: "Transactions",
  average: "Average",
  largest: "Largest",
  share_of_income: "Share of income",
};

export const PARAMETER_LABELS: Record<ParameterName, string> = {
  top_n: "Show top",
  granularity: "Group dates by",
  measure: "Measure",
  comparison: "Compare with",
};

// What each switch in the panel editor says; the parameter it follows is in the catalogue.
export const BIND_LABELS: Record<BindField, string> = {
  limit: "Show the dashboard's top N",
  granularity: "Group dates as the dashboard does",
  measure: "Use the dashboard's measure",
  compare: "Compare as the dashboard does",
  vs: "Measure the change as the dashboard does",
};

export const COMPARISON_LABELS: Record<DashboardParameters["comparison"], string> = {
  previous: "The previous period",
  year_ago: "The same period a year ago",
};

export const CHANGE_VS_LABELS: Record<NonNullable<TableCalc["vs"]>, string> = {
  previous: "the previous period",
  year_ago: "the same period a year ago",
};

export const CHANGE_AS_LABELS: Record<NonNullable<TableCalc["as"]>, string> = {
  percent: "%",
  amount: "Amount",
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
export function bucketEnd(start: string, granularity: Granularity): string {
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

export function isCountLike(config: Pick<PanelConfig, "y">): boolean {
  return config.y.measure === "count" || config.y.agg === "count";
}

// A table calculation can turn values into percentages ("12.5" means 12.5%), and so can a
// calculated field shown as a percentage.
export function isPercent(config: Pick<PanelConfig, "calc"> & { y?: PanelConfig["y"] }): boolean {
  if (config.calc?.type === "percent_of_total" || (config.calc?.type === "change" && config.calc.as !== "amount")) {
    return true;
  }
  // A moving average or a change "as amount" keeps the formula's own unit.
  return isFormula(config) && config.y?.formula?.as === "percent";
}

export function isFormula(config: { y?: PanelConfig["y"] }): boolean {
  return config.y?.measure === "formula";
}

// Values written without a ₹ sign: counts, and calculated fields shown as plain numbers. A change
// "as amount" keeps the panel's own unit, so a plain-number formula stays plain.
export function isPlainNumber(config: Pick<PanelConfig, "y" | "calc">): boolean {
  return isCountLike(config) || (isFormula(config) && config.y.formula?.as === "number");
}

export function formatValue(value: Cell, config: Pick<PanelConfig, "y" | "calc">): string {
  if (value === null) return "–";
  if (isPercent(config)) return `${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 1 })}%`;
  if (isFormula(config) && config.y.formula?.as === "number") {
    return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }
  if (isCountLike(config)) {
    // An average of counts has decimals; a plain count doesn't.
    const decimals = config.calc?.type === "moving_average" ? 2 : 0;
    return Number(value).toLocaleString("en-IN", { maximumFractionDigits: decimals });
  }
  return money(value);
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

// Category name (lower case) -> colour: what the charts use as each category's default colour.
// A category and a data source can share a name, so a source's key has its own prefix.
export const sourceColorKey = (name: string) => `source:${name.toLowerCase()}`;

export function categoryColorMap(categories: Category[], sources: DataSource[] = []): Map<string, string> {
  return new Map([
    ...categories.map((c): [string, string] => [c.name.toLowerCase(), c.color]),
    ...sources.map((s): [string, string] => [sourceColorKey(s.name), s.color]),
  ]);
}

// --- building specs in the editor --------------------------------------------------

export const EMPTY_FILTERS: PanelFilters = {
  date: { preset: "inherit" },
  type: null,
  categories: [],
  data_sources: [],
  merchant_contains: "",
};

export const DEFAULT_DASHBOARD_FILTERS: PanelFilters = {
  ...EMPTY_FILTERS,
  date: { preset: "last_3_months" },
};

// --- dashboard parameters ------------------------------------------------------------

export const BIND_FIELDS: BindField[] = ["limit", "granularity", "measure", "compare", "vs"];

// Whether this panel has the field that a parameter would drive (spec._bindable).
export function bindingAllowed(config: PanelConfig, field: BindField): boolean {
  if (field === "limit") return ["bar", "pie", "donut", "heatmap"].includes(config.chart);
  if (field === "granularity") return config.x?.field === "date";
  if (field === "measure") return config.y.measure !== "formula"; // a formula is the panel's own
  if (field === "compare") return config.chart === "kpi";
  return config.calc?.type === "change";
}

// The bindings as the backend will store them: only fields this draft has, each to its parameter.
function normalizeBind(config: PanelConfig, catalogue: Catalogue): Bindings | undefined {
  const bind: Bindings = {};
  for (const field of BIND_FIELDS) {
    if (config.bind?.[field] && bindingAllowed(config, field)) bind[field] = catalogue.parameters.bindings[field];
  }
  return Object.keys(bind).length ? bind : undefined;
}

// The parameters at least one panel follows, in a fixed order: the dashboard shows a control
// for each of these and no others.
export function usedParameters(panels: { config: AnyPanelConfig | null }[]): ParameterName[] {
  const used = new Set<ParameterName>();
  for (const { config } of panels) {
    if (config && !isText(config)) Object.values(config.bind ?? {}).forEach((name) => used.add(name));
  }
  return PARAMETER_ORDER.filter((name) => used.has(name));
}

const PARAMETER_ORDER: ParameterName[] = ["top_n", "granularity", "measure", "comparison"];

// --- formatting ----------------------------------------------------------------------

export function defaultFormat(): FormatOptions {
  return { labels: false, number: "auto", legend: "auto", axis: { min: null, max: null } };
}

const finiteOrNull = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

// The format options as the backend will store them: defaults filled in, and the options this
// chart doesn't have (a pie has no axis) reset. Undefined for charts without any.
function normalizeFormat(config: PanelConfig, catalogue: Catalogue): FormatOptions | undefined {
  const rules = catalogue.format;
  if (!rules.charts.includes(config.chart)) return undefined;
  const given = { ...defaultFormat(), ...config.format };
  const hasLegend = rules.legend_charts.includes(config.chart);
  const hasAxis = rules.axis_charts.includes(config.chart);
  return {
    labels: given.labels === true,
    number: rules.numbers.includes(given.number) ? given.number : "auto",
    legend: hasLegend && rules.legends.includes(given.legend) ? given.legend : "auto",
    axis: hasAxis
      ? { min: finiteOrNull(given.axis?.min), max: finiteOrNull(given.axis?.max) }
      : { min: null, max: null },
  };
}

// --- KPI cards ---------------------------------------------------------------------

export function defaultKpi(): KpiOptions {
  return { compare: "none", sparkline: null, direction: "auto", secondary: [] };
}

// Whether a small figure can run on this draft, by the catalogue's rules (spec._validate_secondary).
export function figureAllowed(config: PanelConfig, catalogue: Catalogue, figure: KpiFigure): boolean {
  const rule = catalogue.kpi.secondary.find((f) => f.id === figure);
  if (!rule || config.chart !== "kpi") return false;
  if (rule.needs_money_measure && !catalogue.kpi.money_measures.includes(config.y.measure)) return false;
  return !rule.needs_sum || config.y.agg === "sum";
}

// The KPI options as the backend will store them: defaults filled in, and anything this draft
// can't use removed. Undefined for any other chart.
function normalizeKpi(config: PanelConfig, catalogue: Catalogue): KpiOptions | undefined {
  if (config.chart !== "kpi") return undefined;
  const given = { ...defaultKpi(), ...config.kpi };
  const [low, high] = catalogue.kpi.average_of;
  const kpi: KpiOptions = {
    compare: catalogue.kpi.compares.includes(given.compare) ? given.compare : "none",
    sparkline: given.sparkline,
    direction: catalogue.kpi.directions.includes(given.direction) ? given.direction : "auto",
    secondary: [...new Set(given.secondary)]
      .filter((figure) => figureAllowed(config, catalogue, figure))
      .slice(0, catalogue.kpi.max_secondary),
  };
  if (kpi.compare === "average") {
    const days = Number.isInteger(given.average_of) ? (given.average_of as number) : 3;
    kpi.average_of = Math.min(Math.max(days, low), high);
  }
  return kpi;
}

// Whether a change is good news, bad news, or neither. "auto" follows the measure: spending
// less is good, and for everything else (income, net, balance...) more is good.
export type Tone = "good" | "bad" | "flat";

export function kpiTone(change: number | null, kpi: Pick<KpiOptions, "direction">, measure: Measure): Tone {
  if (change === null || change === 0) return "flat";
  const upIsGood = kpi.direction === "up_is_good" || (kpi.direction === "auto" && measure !== "spend");
  return change > 0 === upIsGood ? "good" : "bad";
}

// "vs ₹950.00 before": what the change is measured against.
export function baselineText(kpi: KpiOptions, formatted: string): string {
  if (kpi.compare === "year_ago") return `vs ${formatted} a year ago`;
  if (kpi.compare === "average") return `vs an average of ${formatted} over the ${kpi.average_of} periods before`;
  return `vs ${formatted} before`;
}

// The comparison number. A mean of period counts keeps one decimal ("12.5"); a single count doesn't.
export function formatBaseline(value: Cell, config: Pick<PanelConfig, "y" | "kpi">): string {
  if (value !== null && config.kpi?.compare === "average" && isCountLike(config)) {
    return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 1 });
  }
  return formatValue(value, config);
}

export function formatFigure(figure: KpiFigure, value: string | null): string {
  if (value === null) return "–";
  if (figure === "count") return Number(value).toLocaleString("en-IN");
  return figure === "share_of_income" ? `${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 1 })}%` : money(value);
}

// Charts that group values along x, the only ones with table calculations (engine.GROUPED_CHARTS).
export const GROUPED_CHARTS: DataChartType[] = ["bar", "line", "area", "pie", "donut"];

// Whether a table calculation can run on this draft, by the catalogue's rules (spec.validate_calc).
export function calcAllowed(config: PanelConfig, catalogue: Catalogue, type: CalcType): boolean {
  const rule = catalogue.calcs.find((c) => c.id === type);
  if (!rule || !GROUPED_CHARTS.includes(config.chart)) return false;
  if (rule.needs_date && config.x?.field !== "date") return false;
  if (rule.additive_only && config.y.agg !== "sum" && config.y.agg !== "count") return false;
  if (rule.never_negative && (config.y.measure === "net" || config.y.measure === "balance")) return false;
  return true;
}

// The calculation with its options filled in and the ones it doesn't use removed, as the backend
// will store it; undefined when it can't run on this draft.
function normalizeCalc(config: PanelConfig, catalogue: Catalogue): TableCalc | undefined {
  const calc = config.calc;
  if (!calc || !calcAllowed(config, catalogue, calc.type)) return undefined;
  if (calc.type === "moving_average") {
    const [low, high] = catalogue.limits.window;
    const window = Number.isInteger(calc.window) ? Math.min(Math.max(calc.window as number, low), high) : 3;
    return { type: calc.type, window };
  }
  if (calc.type === "change") return { type: calc.type, vs: calc.vs ?? "previous", as: calc.as ?? "percent" };
  return { type: calc.type };
}

// A sensible starting point for each chart type, used by "Add panel" and the type picker.
export function defaultConfig(chart: DataChartType): PanelConfig {
  const base: PanelConfig = {
    v: 1, // normalizeConfig stamps the catalogue's current version
    chart,
    y: { measure: "spend", agg: "sum" },
    sort: "measure_desc",
    limit: 10,
    bins: 20,
    stacked: false,
    orientation: "vertical",
    series_colors: {},
    filters: EMPTY_FILTERS,
  };
  if (chart === "kpi") return { ...base, kpi: { ...defaultKpi(), compare: "previous" } };
  if (chart === "line" || chart === "area") return { ...base, x: { field: "date", granularity: "month" } };
  if (chart === "histogram" || chart === "calendar") return base;
  if (chart === "heatmap") return { ...base, x: { field: "weekday" }, rows: { field: "category" } };
  return { ...base, x: { field: "category" } };
}

export function formulaAllowed(chart: ChartType, catalogue: Catalogue): boolean {
  return (catalogue.formula.charts as ChartType[]).includes(chart);
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

  // A heatmap's rows: a catalogue field other than x, keeping the user's pick when it still fits.
  if (config.chart === "heatmap") {
    const options = catalogue.rows_fields.filter((field) => field !== next.x?.field);
    const kept = config.rows && options.includes(config.rows.field) ? config.rows.field : undefined;
    next.rows = { field: kept ?? (options.includes("category") ? "category" : options[0]) };
  } else {
    delete next.rows;
  }

  if (config.y.measure === "formula" && formulaAllowed(config.chart, catalogue)) {
    const formula = config.y.formula ?? DEFAULT_FORMULA;
    next.y = {
      measure: "formula",
      agg: catalogue.formula.agg,
      formula: {
        expression: formula.expression.slice(0, catalogue.formula.max_length), // checked on the server
        as: catalogue.formula.forms.includes(formula.as) ? formula.as : catalogue.formula.forms[0],
      },
    };
  } else {
    const measures = measuresFor(config.chart, catalogue);
    const measure = measures.find((m) => m.id === config.y.measure) ?? measures[0];
    next.y = {
      measure: measure.id,
      agg: measure.aggs.includes(config.y.agg) ? config.y.agg : measure.default_agg,
    };
  }

  if (!rules.color || !config.color || config.color.field === next.x?.field || config.color.field === "date") {
    delete next.color;
  }
  const kpi = normalizeKpi(next, catalogue);
  if (kpi) next.kpi = kpi;
  else delete next.kpi;
  const format = normalizeFormat(next, catalogue);
  if (format) next.format = format;
  else delete next.format;
  const bind = normalizeBind(next, catalogue);
  if (bind) next.bind = bind;
  else delete next.bind;
  if (!next.color) next.stacked = false;

  const calc = normalizeCalc(next, catalogue);
  if (calc) next.calc = calc;
  else delete next.calc;
  next.v = catalogue.version;
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
  picked: Picked,
  categories: Category[],
  sources: DataSource[] = [],
): string | null {
  let from = result.period.from;
  let to = result.period.to;
  let type = filters.type;
  let category = filters.categories.length === 1 ? filters.categories[0] : null;
  let shown = filters.data_sources;

  const apply = (field: Dimension | undefined, value: Cell, granularity?: Granularity) => {
    if (value === null || field === undefined) return;
    if (field === "category") {
      const match = categories.find((c) => c.name.toLowerCase() === String(value).toLowerCase());
      if (match) category = match.id; // "Other" (the folded rest) has no single category
    } else if (field === "data_source") {
      const match = sources.find((s) => s.name.toLowerCase() === String(value).toLowerCase());
      if (match) shown = [match.id];
    } else if (field === "txn_type" && (value === "credit" || value === "debit")) {
      type = value;
    } else if (field === "date" && granularity && typeof value === "string") {
      if (value > from) from = value;
      const end = bucketEnd(value, granularity);
      if (end < to) to = end;
    }
  };
  if (config.chart === "calendar" && typeof picked.x === "string") {
    from = picked.x; // a calendar cell is one day
    to = picked.x;
  } else {
    apply(config.x?.field, picked.x, config.x?.granularity);
  }
  apply(config.color?.field, picked.color ?? null);
  apply(config.rows?.field, picked.row ?? null);

  const params = new URLSearchParams({ from, to });
  if (type) params.set("type", type);
  if (category) params.set("category", category);
  if (shown.length) params.set("data_source", shown.join(","));
  return `/transactions?${params}`;
}

// A panel's own filters win; empty ones fall back to the dashboard's (as on the backend).
export function effectiveFilters(panel: PanelFilters, dashboard: PanelFilters): PanelFilters {
  return {
    date: panel.date.preset === "inherit" ? dashboard.date : panel.date,
    type: panel.type ?? dashboard.type,
    categories: panel.categories.length ? panel.categories : dashboard.categories,
    data_sources: panel.data_sources.length ? panel.data_sources : dashboard.data_sources,
    merchant_contains: panel.merchant_contains || dashboard.merchant_contains,
  };
}
