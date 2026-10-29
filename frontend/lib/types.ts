import type { FontChoice } from "@/lib/fonts";

// A word or phrase that helps the AI recognise a category. The category's own name is
// always used too, so it is not listed here.
export type Keyword = { id: string; term: string };

export type Category = {
  id: string;
  name: string;
  is_default: boolean;
  color: string; // "#RRGGBB": the default colour of this category in every chart
  keywords: Keyword[];
};

export type Transaction = {
  id: string;
  date: string; // YYYY-MM-DD
  txn_type: "credit" | "debit";
  category: string; // category id
  name: string;
  description: string;
  amount: string; // decimal as a string, always positive: the sign lives in txn_type
  balance: string | null;
  notes: string; // the user's own optional note ("" when none); also read by the AI
};


// DRF page-number pagination
export type Page<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

// --- statement import ---

export type MappingField =
  | "date"
  | "description"
  | "debit"
  | "credit"
  | "amount"
  | "type"
  | "balance";

// field -> column index in the statement table
export type Mapping = Partial<Record<MappingField, number>>;

export type PreviewRow = {
  row: number;
  date: string;
  txn_type: "credit" | "debit";
  amount: string;
  balance: string | null;
  name: string;
  description: string;
};

export type ImportRowError = { row: number; reason: string };

export type Preview = {
  headers: string[];
  detected_mapping: Mapping;
  sample: PreviewRow[];
  row_count: number;
  error_count: number;
  errors: ImportRowError[];
};

export type ImportResult = {
  imported: number;
  duplicates: number;
  errors: ImportRowError[];
};

// --- AI categorisation ---

// `digest` identifies the exact model build: a tag can point at a new one after `ollama pull`.
export type EmbeddingModel = { name: string; dimension: number | null; digest?: string };

export type ProposalDecision = "propose" | "below_threshold" | "too_close" | "no_candidates";

export type Proposal = {
  transaction: string; // transaction id
  date: string;
  txn_type: "credit" | "debit";
  name: string;
  amount: string;
  category: string | null; // best guess (category id), even when the decision isn't "propose"
  category_name: string | null;
  score: number | null; // cosine similarity, 0-1
  runner_up: string | null;
  runner_up_name: string | null;
  runner_up_score: number | null;
  decision: ProposalDecision;
};

export type CategorizePreview = {
  model: string;
  considered: number;
  proposed: number;
  skipped: number;
  capped: boolean; // more uncategorised rows exist than one run scores
  proposals: Proposal[];
};

// GET /api/ai/categorize/prepare/: what the browser embeds with the user's own Ollama and
// scores itself. Every number in `label`, `examples` and `text` is an index into `texts`.
export type Candidate = { category: string; name: string; label: number; examples: number[] };

export type PreparedTarget = {
  transaction: string;
  date: string;
  txn_type: "credit" | "debit";
  name: string;
  amount: string;
  text: number;
};

export type PreparedRun = {
  considered: number;
  capped: boolean;
  thresholds: { min_score: number; min_margin: number; blend_full_at: number; blend_max_weight: number };
  texts: string[];
  candidates: Partial<Record<"credit" | "debit", Candidate[]>>;
  targets: PreparedTarget[];
};

export type ApplyResult = {
  applied: number;
  skipped: { transaction: string; reason: "invalid_category" | "not_in_others" }[];
};

// --- RAG ("Ask your transactions") ---
// These mirror backend/ai/rag_views.py. The browser embeds with the user's own Ollama; the
// server stores the encrypted index, searches it and builds the prompt.

export type ChatModel = { name: string };

export type RagProfile = { doc_prefix: string; query_prefix: string; tuned: boolean };

// GET /api/ai/rag/status/
export type RagStatus = { enabled: boolean; indexed: number; total: number; profile: RagProfile };

// GET /api/ai/rag/pending/: `version` must come back with the vector.
export type PendingItem = { transaction: string; version: string; text: string };
export type PendingBatch = { items: PendingItem[]; remaining: number };

// POST /api/ai/rag/vectors/
export type VectorItem = { transaction: string; version: string; vector: number[] };
export type StoreResult = { stored: number; stale: number; rejected: number };

export type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

export type AskFilters = { date: DateFilter; type: "credit" | "debit" | null };

export type RagSource = {
  n: number; // the number the model cites as [n]
  transaction: string;
  date: string;
  txn_type: "credit" | "debit";
  amount: string;
  name: string;
  category: { id: string; name: string; color: string };
};

export type RagPeriod = { from: string; to: string; source: "question" | "filter"; phrase: string | null };

// searched < indexed: the per-ask cap was hit; indexed < total: some rows aren't embedded yet.
export type RagCoverage = { searched: number; indexed: number; total: number };

export type RagSummary = {
  matches: number;
  debit_total: string;
  credit_total: string;
  first_date: string | null;
  last_date: string | null;
};

// POST /api/ai/rag/ask/. `messages` is null when nothing matched: the model isn't called.
export type AskResponse = {
  prompt_version: string;
  profile: RagProfile;
  period: RagPeriod;
  coverage: RagCoverage;
  summary: RagSummary;
  sources: RagSource[];
  in_prompt: number; // sources 1..in_prompt are in the prompt; higher citations are invalid
  messages: ChatMessage[] | null;
  options: Record<string, number>;
};

// --- AI panel builder (/api/ai/agent/) ---

export type AgentStatus = {
  enabled: boolean;
  prompt_version: string;
  limits: { message: number; reply: number; turns: number; steps: number };
};

// What the browser asks the user's Ollama for, on the server's behalf.
export type AgentChatRequest = {
  kind: "chat";
  messages: ChatMessage[];
  format: object; // a JSON schema: the reply must be JSON of this shape
  options: Record<string, number>;
};
export type AgentEmbedRequest = { kind: "embed"; model: string; text: string };

export type AgentOutcome =
  | {
      kind: "preview";
      title: string; // the model's suggestion, or the summary
      summary: string; // written by the server from the panel's config
      config: PanelConfig;
      result: QueryResult;
      notes: string[]; // what the server changed or could not match
    }
  | { kind: "not_a_panel"; reason: string }
  | { kind: "failed"; code: string; detail: string; config?: PanelConfig; title?: string };

export type AgentResponse =
  | {
      status: "needs_model";
      token: string;
      progress: { label: string; attempt: number };
      request: AgentChatRequest | AgentEmbedRequest;
    }
  | { status: "done"; token: string; outcome: AgentOutcome };

// The dashboard the panel is for: its filter bar and parameters shape the preview.
export type AgentDashboard = { filters: PanelFilters; parameters: DashboardParameters | null };

// --- Insights (dashboards of chart panels) ---
// These mirror backend/insights/spec.py. The backend validates every spec, so these types
// help the editor build valid ones; they are not the security boundary.

export type ChartType =
  | "kpi"
  | "bar"
  | "line"
  | "area"
  | "pie"
  | "donut"
  | "histogram"
  | "calendar"
  | "heatmap"
  | "text";
// Every chart that shows data. A text panel is a note: it has no measure, filters or query.
export type DataChartType = Exclude<ChartType, "text">;
export type Granularity = "day" | "week" | "month" | "quarter" | "year";
export type Dimension = "date" | "weekday" | "month_of_year" | "category" | "txn_type" | "merchant";
// "formula" is a calculated field: a number the panel works out from each group's totals.
export type Measure = "spend" | "income" | "net" | "amount" | "count" | "balance" | "formula";
// How a calculated field's result reads: a plain number, a percentage, or money.
export type FormulaForm = "number" | "percent" | "money";
export type Formula = { expression: string; as: FormulaForm };
// The formula language as the catalogue describes it, for the editor's reference list.
export type FormulaVariable = { name: string; help: string };
export type FormulaField = { name: string; type: "number" | "text" | "date"; help: string };
export type FormulaFunctionGroup = "aggregate" | "logic" | "number" | "text" | "date";
export type FormulaFunction = { name: string; signature: string; group: FormulaFunctionGroup; help: string };
export type Agg = "sum" | "avg" | "min" | "max" | "median" | "count" | "last";
export type DatePreset =
  | "this_month"
  | "last_month"
  | "last_3_months"
  | "last_12_months"
  | "this_year"
  | "all"
  | "custom";

// "inherit" (panels only) means "use the dashboard's date range".
export type DateFilter = { preset: DatePreset | "inherit"; from?: string; to?: string };

export type PanelFilters = {
  date: DateFilter;
  type: "credit" | "debit" | null;
  categories: string[]; // category ids
  merchant_contains: string;
};

// A validated panel config, exactly as the backend returns it (every default filled in).
// Table calculations, computed on the aggregated chart values (backend/insights/engine.py).
export type CalcType = "running_total" | "percent_of_total" | "moving_average" | "change";
export type TableCalc = {
  type: CalcType;
  window?: number; // moving_average: buckets averaged
  vs?: "previous" | "year_ago"; // change: compared with
  as?: "percent" | "amount"; // change: shown as
};

// What a KPI card shows besides its number (backend/insights/spec.py validate_kpi).
export type KpiCompare = "none" | "previous" | "year_ago" | "average";
export type KpiDirection = "auto" | "up_is_good" | "down_is_good";
export type KpiFigure = "count" | "average" | "largest" | "share_of_income";
export type KpiOptions = {
  compare: KpiCompare;
  average_of?: number; // compare "average": how many earlier periods
  sparkline: Granularity | null; // the trend line's time step, or none
  direction: KpiDirection; // which way of change is good news
  secondary: KpiFigure[]; // the small figures under the number
};

// Presentation options for charts (backend/insights/spec.py validate_format). The engine never
// reads them, so they cannot change a chart's numbers.
export type NumberFormat = "auto" | "full" | "compact";
export type LegendPosition = "auto" | "top" | "bottom" | "right" | "none";
export type FormatOptions = {
  labels: boolean; // values written on the bars, points and slices
  number: NumberFormat; // auto: compact on axes, full in tooltips
  legend: LegendPosition; // auto: the chart's own default
  axis: { min: number | null; max: number | null }; // value-axis bounds
};

// Dashboard parameters (backend/insights/spec.py): a few values the whole dashboard shares. A
// panel follows one only where it is bound to it (`bind`); an unbound field keeps its own value.
export type ParameterName = "top_n" | "granularity" | "measure" | "comparison";
export type DashboardParameters = {
  top_n: number;
  granularity: Granularity;
  measure: "spend" | "income" | "net";
  comparison: "previous" | "year_ago";
};
export type BindField = "limit" | "granularity" | "measure" | "compare" | "vs";
export type Bindings = Partial<Record<BindField, ParameterName>>;

export type PanelConfig = {
  v: number; // the spec version; the backend upgrades older ones
  chart: DataChartType;
  x?: { field: Dimension; granularity?: Granularity };
  rows?: { field: Dimension }; // a heatmap's second axis
  y: { measure: Measure; agg: Agg; formula?: Formula }; // formula only with measure "formula"
  color?: { field: Dimension };
  sort: "measure_desc" | "label";
  limit: number;
  bins: number;
  kpi?: KpiOptions;
  calc?: TableCalc;
  format?: FormatOptions;
  bind?: Bindings;
  stacked: boolean;
  orientation: "vertical" | "horizontal";
  // The user's colour overrides: raw series value (a category name, "credit"...) -> "#RRGGBB".
  // The key "_" colours a chart that has a single series.
  series_colors: Record<string, string>;
  filters: PanelFilters;
};

// A note on the dashboard: just its words, shown as formatted text and never as markup.
export type TextConfig = { v: number; chart: "text"; text: string };

export type AnyPanelConfig = PanelConfig | TextConfig;

export function isText(config: AnyPanelConfig): config is TextConfig {
  return config.chart === "text";
}

export type Panel = {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  show_title: boolean; // false: the panel is drawn without its header line
  config: AnyPanelConfig | null; // null when a saved config no longer validates
  config_error?: string;
};

export type DashboardSummary = { id: string; name: string; position: number };
export type DashboardDetail = DashboardSummary & {
  panels: Panel[];
  settings: { parameters: DashboardParameters };
};

// GET /api/insights/fields/: what the panel editor may offer.
export type Catalogue = {
  version: number;
  dimensions: { id: Dimension; granularities: Granularity[] }[];
  measures: { id: Measure; aggs: Agg[]; default_agg: Agg }[];
  charts: Record<ChartType, { x: Dimension[]; color: boolean }>;
  calcs: { id: CalcType; needs_date: boolean; additive_only: boolean; never_negative: boolean }[];
  kpi: {
    compares: KpiCompare[];
    directions: KpiDirection[];
    secondary: { id: KpiFigure; needs_money_measure: boolean; needs_sum: boolean }[];
    money_measures: Measure[];
    average_of: [number, number];
    max_secondary: number;
  };
  rows_fields: Dimension[]; // what a heatmap's rows can be
  formula: {
    charts: DataChartType[]; // where a calculated field can be used
    agg: Agg; // the one aggregation a formula panel stores
    forms: FormulaForm[];
    max_length: number;
    variables: FormulaVariable[]; // totals for the whole group: spend, income...
    fields: FormulaField[]; // one value per transaction, written in brackets
    functions: FormulaFunction[];
    keywords: string[];
  };
  parameters: {
    defaults: DashboardParameters;
    measures: DashboardParameters["measure"][];
    comparisons: DashboardParameters["comparison"][];
    top_n: [number, number];
    bindings: Record<BindField, ParameterName>;
  };
  format: {
    numbers: NumberFormat[];
    legends: LegendPosition[];
    charts: DataChartType[];
    legend_charts: DataChartType[];
    axis_charts: DataChartType[];
  };
  change_vs: NonNullable<TableCalc["vs"]>[];
  change_as: NonNullable<TableCalc["as"]>[];
  sorts: PanelConfig["sort"][];
  orientations: PanelConfig["orientation"][];
  txn_types: ("credit" | "debit")[];
  date_presets: DatePreset[];
  limits: {
    limit: [number, number];
    bins: [number, number];
    categories: number;
    merchant_contains: number;
    window: [number, number];
    text: number;
    calendar_days: number;
  };
};

export type Cell = string | number | null;

export type QueryResult = {
  columns: string[]; // ["x", "value"], ["x", "color", "value"], ["value", "previous", "change_pct"] ...
  rows: Cell[][];
  meta: { chart: ChartType };
  period: { from: string; to: string };
  // A KPI only: the trend line, and the small figures under the number.
  sparkline?: { granularity: Granularity; columns: string[]; rows: Cell[][] };
  // A heatmap only: every x and row value in display order, so empty cells can be placed.
  axes?: { x: Cell[]; rows: Cell[] };
  secondary?: { id: KpiFigure; value: string | null }[];
};

// A clicked mark, as the backend reads it (insights.spec.validate_selection): every key is
// optional, and categories / merchants are names as a chart labels them.
export type Selection = {
  categories?: string[];
  merchants?: string[];
  type?: "credit" | "debit";
  weekdays?: number[]; // 0 = Monday
  months?: number[]; // 1-12
  date?: { from: string; to: string };
};

// What a click on a chart landed on, in the backend's raw values: the x value, the colour
// series if the chart has one, and a heatmap's row.
export type Picked = { x: Cell; color?: Cell; row?: Cell };

// A page of the transactions behind a mark (POST /api/insights/rows/).
export type RowsPage = {
  total: number;
  value: string | null; // what the chart shows for these rows
  totals: { debit: string; credit: string };
  period: { from: string; to: string };
  rows: { date: string; name: string; category: string; txn_type: "credit" | "debit"; amount: string }[];
};

export type QueryError = { error: { code: string; detail: string } };
export type QueryOutcome = QueryResult | QueryError;

// --- Preferences (Settings page) ---

export type { FontChoice } from "@/lib/fonts";

// "quality": charts are sharp vector graphics (SVG). "performance": a pixel canvas, faster
// for charts with thousands of points.
export type ChartQuality = "quality" | "performance";

export type Preferences = { font: FontChoice; chart_quality: ChartQuality };
