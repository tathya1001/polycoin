"use client";

import { CalendarDays, ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/cn";
import { PRESET_LABELS, todayLocal } from "@/lib/insights";
import type { Category, DataSource, DatePreset, PanelFilters } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";
import CategoryPicker from "./CategoryPicker";
import SourcePicker from "./SourcePicker";

const PRESETS: DatePreset[] = [
  "this_month",
  "last_month",
  "last_3_months",
  "last_12_months",
  "this_year",
  "all",
  "custom",
];

const MONEY_OPTIONS: { value: "" | "debit" | "credit"; label: string }[] = [
  { value: "", label: "In and out" },
  { value: "debit", label: "Money out" },
  { value: "credit", label: "Money in" },
];

type Props = {
  filters: PanelFilters;
  categories: Category[];
  sources: DataSource[];
  onChange: (next: PanelFilters) => void;
};

function dateSummary(date: PanelFilters["date"]): string {
  if (date.preset === "custom" && date.from && date.to) return `${date.from} → ${date.to}`;
  return PRESET_LABELS[date.preset];
}

// The dashboard's filters, shown as pills that open a popover.
// They apply to every panel, except where a panel pins its own. Changing one re-runs every
// panel in a single request.
export default function FilterBar({ filters, categories, sources, onChange }: Props) {
  const date = filters.date;

  function setPreset(preset: DatePreset) {
    if (preset !== "custom") return onChange({ ...filters, date: { preset } });
    // Start a custom range from this month, so both dates are always filled in.
    const today = todayLocal();
    onChange({ ...filters, date: { preset, from: `${today.slice(0, 8)}01`, to: today } });
  }

  const moneyLabel = MONEY_OPTIONS.find((o) => o.value === (filters.type ?? ""))?.label ?? "In and out";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Popover
        trigger={(p) => (
          <Button
            size="sm"
            icon={<CalendarDays size={15} />}
            aria-label={`Date range: ${dateSummary(date)}`}
            onClick={p.onClick}
            aria-expanded={p["aria-expanded"]}
            aria-haspopup={p["aria-haspopup"]}
          >
            {dateSummary(date)}
            <ChevronDown size={14} aria-hidden />
          </Button>
        )}
        className="w-60"
      >
        <ul className="flex flex-col gap-0.5">
          {PRESETS.map((preset) => (
            <li key={preset}>
              <button
                type="button"
                onClick={() => setPreset(preset)}
                aria-pressed={date.preset === preset}
                className={cn(
                  "flex w-full items-center justify-between rounded-sm px-2.5 py-1.5 text-left text-sm hover:bg-wash",
                  date.preset === preset && "font-semibold",
                )}
              >
                {PRESET_LABELS[preset]}
                {date.preset === preset && <Check size={15} aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
        {date.preset === "custom" && (
          <div className="mt-3 grid grid-cols-2 gap-2 border-t border-hairline pt-3">
            <label className="space-y-1 text-xs font-medium">
              From
              <Input
                dense
                type="date"
                value={date.from ?? ""}
                max={date.to}
                onChange={(e) => e.target.value && onChange({ ...filters, date: { ...date, from: e.target.value } })}
              />
            </label>
            <label className="space-y-1 text-xs font-medium">
              To
              <Input
                dense
                type="date"
                value={date.to ?? ""}
                min={date.from}
                onChange={(e) => e.target.value && onChange({ ...filters, date: { ...date, to: e.target.value } })}
              />
            </label>
          </div>
        )}
      </Popover>

      <Popover
        trigger={(p) => (
          <Button
            size="sm"
            aria-label={`Money: ${moneyLabel}`}
            onClick={p.onClick}
            aria-expanded={p["aria-expanded"]}
            aria-haspopup={p["aria-haspopup"]}
          >
            {moneyLabel}
            <ChevronDown size={14} aria-hidden />
          </Button>
        )}
        className="w-44"
      >
        {(close) => (
          <ul className="flex flex-col gap-0.5">
            {MONEY_OPTIONS.map((option) => (
              <li key={option.value}>
                <button
                  type="button"
                  onClick={() => {
                    onChange({ ...filters, type: (option.value || null) as PanelFilters["type"] });
                    close();
                  }}
                  className={cn(
                    "flex w-full items-center justify-between rounded-sm px-2.5 py-1.5 text-left text-sm hover:bg-wash",
                    (filters.type ?? "") === option.value && "font-semibold",
                  )}
                >
                  {option.label}
                  {(filters.type ?? "") === option.value && <Check size={15} aria-hidden />}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Popover>

      <CategoryPicker
        categories={categories}
        selected={filters.categories}
        onChange={(ids) => onChange({ ...filters, categories: ids })}
      />
      <SourcePicker
        sources={sources}
        selected={filters.data_sources}
        onChange={(ids) => onChange({ ...filters, data_sources: ids })}
      />
    </div>
  );
}
