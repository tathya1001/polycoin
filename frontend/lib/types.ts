// A word or phrase that helps the AI recognise a category. The category's own name is
// always used too, so it is not listed here.
export type Keyword = { id: string; term: string };

export type Category = {
  id: string;
  name: string;
  is_default: boolean;
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

// --- Excel import ---

export type MappingField =
  | "date"
  | "description"
  | "debit"
  | "credit"
  | "amount"
  | "type"
  | "balance";

// field -> column index in the sheet
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

export type EmbeddingModel = { name: string; dimension: number | null };

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

export type ApplyResult = {
  applied: number;
  skipped: { transaction: string; reason: "invalid_category" | "not_in_others" }[];
};

// --- Insights (dashboards of chart panels) ---
// These mirror backend/insights/spec.py. The backend validates every spec, so these types
// help the editor build valid ones; they are not the security boundary.

export type ChartType = "kpi" | "bar" | "line" | "area" | "pie" | "donut" | "histogram";
export type Granularity = "day" | "week" | "month" | "quarter" | "year";
export type Dimension = "date" | "weekday" | "month_of_year" | "category" | "txn_type" | "merchant";
export type Measure = "spend" | "income" | "net" | "amount" | "count" | "balance";
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
export type PanelConfig = {
  v: 1;
  chart: ChartType;
  x?: { field: Dimension; granularity?: Granularity };
  y: { measure: Measure; agg: Agg };
  color?: { field: Dimension };
  sort: "measure_desc" | "label";
  limit: number;
  bins: number;
  compare: boolean;
  stacked: boolean;
  orientation: "vertical" | "horizontal";
  filters: PanelFilters;
};

export type Panel = {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  config: PanelConfig | null; // null when a saved config no longer validates
  config_error?: string;
};

export type DashboardSummary = { id: string; name: string; position: number };
export type DashboardDetail = DashboardSummary & { panels: Panel[] };

// GET /api/insights/fields/: what the panel editor may offer.
export type Catalogue = {
  version: number;
  dimensions: { id: Dimension; granularities: Granularity[] }[];
  measures: { id: Measure; aggs: Agg[]; default_agg: Agg }[];
  charts: Record<ChartType, { x: Dimension[]; color: boolean }>;
  sorts: PanelConfig["sort"][];
  orientations: PanelConfig["orientation"][];
  txn_types: ("credit" | "debit")[];
  date_presets: DatePreset[];
  limits: { limit: [number, number]; bins: [number, number]; categories: number; merchant_contains: number };
};

export type Cell = string | number | null;

export type QueryResult = {
  columns: string[]; // ["x", "value"], ["x", "color", "value"], ["value", "previous", "change_pct"] ...
  rows: Cell[][];
  meta: { chart: ChartType };
  period: { from: string; to: string };
};

export type QueryError = { error: { code: string; detail: string } };
export type QueryOutcome = QueryResult | QueryError;
