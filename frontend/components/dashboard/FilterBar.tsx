"use client";

import { PRESET_LABELS, todayLocal } from "@/lib/insights";
import type { Category, DatePreset, PanelFilters } from "@/lib/types";
import CategoryPicker from "./CategoryPicker";

const PRESETS: DatePreset[] = [
  "this_month",
  "last_month",
  "last_3_months",
  "last_12_months",
  "this_year",
  "all",
  "custom",
];

type Props = {
  filters: PanelFilters;
  categories: Category[];
  onChange: (next: PanelFilters) => void;
};

// The dashboard's filters (Tableau's dashboard filters): they apply to every panel, except
// where a panel pins its own. Changing one re-runs every panel in a single request.
export default function FilterBar({ filters, categories, onChange }: Props) {
  const date = filters.date;

  function setPreset(preset: DatePreset) {
    if (preset !== "custom") return onChange({ ...filters, date: { preset } });
    // Start a custom range from this month, so both dates are always filled in.
    const today = todayLocal();
    onChange({ ...filters, date: { preset, from: `${today.slice(0, 8)}01`, to: today } });
  }

  return (
    <div className="flex flex-wrap items-end gap-3 text-sm">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-500">Date range</span>
        <select className="border p-1" value={date.preset} onChange={(e) => setPreset(e.target.value as DatePreset)}>
          {PRESETS.map((preset) => (
            <option key={preset} value={preset}>{PRESET_LABELS[preset]}</option>
          ))}
        </select>
      </label>

      {date.preset === "custom" && (
        <>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">From</span>
            <input
              type="date"
              className="border p-1"
              value={date.from ?? ""}
              max={date.to}
              onChange={(e) => e.target.value && onChange({ ...filters, date: { ...date, from: e.target.value } })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">To</span>
            <input
              type="date"
              className="border p-1"
              value={date.to ?? ""}
              min={date.from}
              onChange={(e) => e.target.value && onChange({ ...filters, date: { ...date, to: e.target.value } })}
            />
          </label>
        </>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-500">Money</span>
        <select
          className="border p-1"
          value={filters.type ?? ""}
          onChange={(e) => onChange({ ...filters, type: (e.target.value || null) as PanelFilters["type"] })}
        >
          <option value="">In and out</option>
          <option value="debit">Money out</option>
          <option value="credit">Money in</option>
        </select>
      </label>

      <CategoryPicker
        categories={categories}
        selected={filters.categories}
        onChange={(ids) => onChange({ ...filters, categories: ids })}
      />
    </div>
  );
}
