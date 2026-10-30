// The transactions table's filters: what the headers hold, the query they send, and the chips that
// show them. Pure: no React, no DOM.

import { money } from "@/lib/format";
import type { Category, DataSource } from "@/lib/types";

export type TxnType = "" | "credit" | "debit";

export type TxnFilters = {
  from: string;
  to: string;
  name: string;
  sources: string[];
  type: TxnType;
  amountMin: string;
  amountMax: string;
  balanceMin: string;
  balanceMax: string;
  categories: string[];
  notes: string;
};

export type FilterColumn = "date" | "name" | "source" | "amount" | "balance" | "category" | "notes";

export const NO_FILTERS: TxnFilters = {
  from: "",
  to: "",
  name: "",
  sources: [],
  type: "",
  amountMin: "",
  amountMax: "",
  balanceMin: "",
  balanceMax: "",
  categories: [],
  notes: "",
};

const list = (raw: string | null) => raw?.split(",").filter(Boolean) ?? [];

// A dashboard chart click opens /transactions with some of these in the URL.
export function filtersFromUrl(params: { get: (key: string) => string | null }): TxnFilters {
  const type = params.get("type");
  return {
    ...NO_FILTERS,
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    type: type === "credit" || type === "debit" ? type : "",
    categories: list(params.get("category")),
    sources: list(params.get("data_source")),
  };
}

export function filterParams(filters: TxnFilters, page: number): URLSearchParams {
  const params = new URLSearchParams({ page: String(page) });
  const set = (key: string, value: string) => {
    if (value.trim()) params.set(key, value.trim());
  };
  set("from", filters.from);
  set("to", filters.to);
  set("type", filters.type);
  set("name", filters.name);
  set("notes", filters.notes);
  set("amount_min", filters.amountMin);
  set("amount_max", filters.amountMax);
  set("balance_min", filters.balanceMin);
  set("balance_max", filters.balanceMax);
  set("category", filters.categories.join(","));
  set("data_source", filters.sources.join(","));
  return params;
}

function range(low: string, high: string, show: (value: string) => string): string {
  if (low && high) return `${show(low)} to ${show(high)}`;
  return low ? `from ${show(low)}` : `up to ${show(high)}`;
}

const asMoney = (value: string) => (Number.isFinite(Number(value)) ? money(value) : value);

// One entry per filtered column, with what each chip says and what removing it clears.
export function activeFilters(
  filters: TxnFilters,
  categories: Category[],
  sources: DataSource[],
): { column: FilterColumn; label: string; clear: Partial<TxnFilters> }[] {
  const active: ReturnType<typeof activeFilters> = [];
  const named = (ids: string[], items: { id: string; name: string }[], plural: string) =>
    ids.length === 1 ? (items.find((item) => item.id === ids[0])?.name ?? `1 ${plural}`) : `${ids.length} ${plural}`;

  if (filters.from || filters.to) {
    const label = `Date ${range(filters.from, filters.to, (day) => day)}`;
    active.push({ column: "date", label, clear: { from: "", to: "" } });
  }
  if (filters.name.trim()) {
    active.push({ column: "name", label: `Name has "${filters.name.trim()}"`, clear: { name: "" } });
  }
  if (filters.sources.length) {
    const label = `Source: ${named(filters.sources, sources, "sources")}`;
    active.push({ column: "source", label, clear: { sources: [] } });
  }
  if (filters.type) {
    const label = filters.type === "credit" ? "Money in" : "Money out";
    active.push({ column: "amount", label, clear: { type: "" } });
  }
  if (filters.amountMin || filters.amountMax) {
    const label = `Amount ${range(filters.amountMin, filters.amountMax, asMoney)}`;
    active.push({ column: "amount", label, clear: { amountMin: "", amountMax: "" } });
  }
  if (filters.balanceMin || filters.balanceMax) {
    const label = `Balance ${range(filters.balanceMin, filters.balanceMax, asMoney)}`;
    active.push({ column: "balance", label, clear: { balanceMin: "", balanceMax: "" } });
  }
  if (filters.categories.length) {
    const label = `Category: ${named(filters.categories, categories, "categories")}`;
    active.push({ column: "category", label, clear: { categories: [] } });
  }
  if (filters.notes.trim()) {
    active.push({ column: "notes", label: `Notes have "${filters.notes.trim()}"`, clear: { notes: "" } });
  }
  return active;
}
