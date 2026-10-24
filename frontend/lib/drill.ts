// What a click on a chart means: the filter it stands for, and the next level of detail below it.
// Pure: no React, no DOM.

import { bucketEnd, calcAllowed, formatLabel } from "@/lib/insights";
import type { Catalogue, Category, Cell, Dimension, Granularity, PanelConfig, Picked, QueryResult, Selection } from "@/lib/types";

// What the backend calls the sum of everything past a chart's limit. It stands for many
// categories or merchants, so a click on it has no single thing to filter by or open.
const FOLDED = "Other";

// One level finer than each date grouping. A day has no finer level.
const FINER: Partial<Record<Granularity, Granularity>> = {
  year: "quarter",
  quarter: "month",
  month: "week",
  week: "day",
};

const isFolded = (field: Dimension | undefined, value: Cell) =>
  value === FOLDED && (field === "category" || field === "merchant");

// The clicked mark as a filter for the other panels and for the transaction list.
// Empty when the click stands for nothing a filter can say (a histogram bin, the folded "Other").
export function selectionFor(config: PanelConfig, picked: Picked): Selection {
  const selection: Selection = {};
  const add = (field: Dimension | undefined, value: Cell | undefined, granularity?: Granularity) => {
    if (!field || value === null || value === undefined || isFolded(field, value)) return;
    const text = String(value);
    if (field === "category") selection.categories = [text];
    else if (field === "merchant") selection.merchants = [text];
    else if (field === "txn_type") {
      if (text === "credit" || text === "debit") selection.type = text;
    } else if (field === "weekday") selection.weekdays = [Number(value)];
    else if (field === "month_of_year") selection.months = [Number(value)];
    else if (granularity) selection.date = { from: text, to: bucketEnd(text, granularity) };
  };
  if (config.chart === "calendar") add("date", picked.x, "day");
  else add(config.x?.field, picked.x, config.x?.granularity);
  add(config.color?.field, picked.color);
  add(config.rows?.field, picked.row);
  return selection;
}

export function isEmptySelection(selection: Selection): boolean {
  return Object.keys(selection).length === 0;
}

// "Food", "Mar 2026", "Food · Mar 2026": what a click was on, in words.
export function pickedLabel(config: PanelConfig, picked: Picked): string {
  const parts: string[] = [];
  const add = (field: Dimension | undefined, value: Cell | undefined, granularity?: Granularity) => {
    if (field && value !== null && value !== undefined && !isFolded(field, value)) {
      parts.push(formatLabel(value, field, granularity));
    }
  };
  if (config.chart === "calendar") add("date", picked.x, "day");
  else add(config.x?.field, picked.x, config.x?.granularity);
  add(config.color?.field, picked.color);
  add(config.rows?.field, picked.row);
  return parts.join(" · ");
}

// One step down a drill path: what the user clicked, and the panel as it looks after.
export type DrillStep = { label: string; config: PanelConfig };

const later = (a: string, b: string) => (a > b ? a : b);
const earlier = (a: string, b: string) => (a < b ? a : b);

// The panel one level down inside the clicked mark, or null when there is no level below:
//   - a date axis goes year -> quarter -> month -> week -> day, limited to the clicked bucket
//   - a category axis goes to the merchants inside that category
// The new config is an ordinary config, so the backend needs no idea that it is a drill.
export function drillInto(
  config: PanelConfig,
  result: QueryResult,
  picked: Picked,
  categories: Category[],
  catalogue: Catalogue,
): DrillStep | null {
  const x = config.x;
  if (!x || picked.x === null) return null;

  if (x.field === "date" && x.granularity && typeof picked.x === "string") {
    const finer = FINER[x.granularity];
    if (!finer) return null;
    // Stay inside the period the panel shows: a year bucket can start before it.
    const from = later(picked.x, result.period.from);
    const to = earlier(bucketEnd(picked.x, x.granularity), result.period.to);
    const next: PanelConfig = {
      ...config,
      x: { ...x, granularity: finer },
      filters: { ...config.filters, date: { preset: "custom", from, to } },
    };
    if (config.bind?.granularity) {
      // A panel that follows the dashboard's grouping would jump back to it, so it stops following.
      const rest = { ...config.bind };
      delete rest.granularity;
      if (Object.keys(rest).length) next.bind = rest;
      else delete next.bind;
    }
    return { label: formatLabel(picked.x, "date", x.granularity), config: next };
  }

  if (x.field === "category" && !isFolded("category", picked.x) && config.color?.field !== "merchant") {
    const match = categories.find((c) => c.name.toLowerCase() === String(picked.x).toLowerCase());
    if (!match) return null;
    const next: PanelConfig = {
      ...config,
      x: { field: "merchant" },
      filters: { ...config.filters, categories: [match.id] },
    };
    // Calculations that need a date axis can't follow the chart to merchants.
    if (next.calc && !calcAllowed(next, catalogue, next.calc.type)) delete next.calc;
    return { label: match.name, config: next };
  }
  return null;
}
