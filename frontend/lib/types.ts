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
