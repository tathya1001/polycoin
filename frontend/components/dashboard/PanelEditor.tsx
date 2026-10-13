"use client";

// The panel editor drawer: Tableau's "Show Me" plus shelves, in small form.
//
// Pick a chart type, then fill its slots (x axis, measure, colour...) from dropdowns built
// from the backend's catalogue (GET /api/insights/fields/). Every change is passed through
// normalizeConfig, so the draft always obeys the chart rules, and a live preview re-queries
// the backend half a second after you stop changing things.

import { useEffect, useState, type ReactNode } from "react";
import PanelBody from "@/components/charts/PanelBody";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import {
  AGG_LABELS,
  CHART_ICONS,
  CHART_LABELS,
  DIMENSION_LABELS,
  GRANULARITY_LABELS,
  MEASURE_LABELS,
  PRESET_LABELS,
  QUERY_URL,
  defaultConfig,
  measuresFor,
  normalizeConfig,
  todayLocal,
} from "@/lib/insights";
import type {
  Agg,
  Catalogue,
  Category,
  ChartType,
  DatePreset,
  Dimension,
  Granularity,
  Measure,
  PanelConfig,
  PanelFilters,
  QueryOutcome,
} from "@/lib/types";
import CategoryPicker from "./CategoryPicker";

const PREVIEW_DELAY_MS = 500; // the preview shares the 600/hour "insights" throttle
const MAX_TITLE = 80; // PanelUpdateSerializer.title max_length

type Props = {
  catalogue: Catalogue;
  categories: Category[];
  initial: { title: string; config: PanelConfig };
  isNew: boolean;
  dashboardFilters: PanelFilters;
  onCancel: () => void;
  onSave: (title: string, config: PanelConfig) => Promise<string | null>; // error, or null
};

export default function PanelEditor(props: Props) {
  const { catalogue, categories, initial, isNew, dashboardFilters, onCancel, onSave } = props;
  const [title, setTitle] = useState(initial.title);
  const [config, setConfig] = useState(() => normalizeConfig(initial.config, catalogue));
  const [preview, setPreview] = useState<QueryOutcome | undefined>(undefined);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rules = catalogue.charts[config.chart];
  const measure = catalogue.measures.find((m) => m.id === config.y.measure);
  const categorical = !!config.x && config.x.field !== "date";
  const dimensions = catalogue.dimensions.map((d) => d.id);

  function update(change: Partial<PanelConfig>) {
    setConfig((current) => normalizeConfig({ ...current, ...change }, catalogue));
  }

  function updateFilters(change: Partial<PanelFilters>) {
    setConfig((current) => ({ ...current, filters: { ...current.filters, ...change } }));
  }

  function pickChart(chart: ChartType) {
    // Keep the measure across chart types where it still fits; reset the rest to defaults.
    setConfig((current) =>
      normalizeConfig({ ...defaultConfig(chart), y: current.y, filters: current.filters }, catalogue),
    );
  }

  // Live preview, debounced: only the last change in a burst reaches the backend.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      setPreviewing(true);
      try {
        const res = await apiFetch(QUERY_URL, {
          method: "POST",
          body: JSON.stringify({ filters: dashboardFilters, queries: [{ key: "preview", spec: config }] }),
        });
        if (cancelled) return;
        if (res.ok) {
          setPreview((await res.json()).results.preview);
          setPreviewError(null);
        } else {
          setPreviewError(await readError(res, "Could not preview this panel."));
        }
      } catch {
        if (!cancelled) setPreviewError("Cannot reach the server.");
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [config, dashboardFilters]);

  async function save() {
    setSaving(true);
    setError(null);
    const problem = await onSave(title.trim(), config);
    setSaving(false);
    if (problem) setError(problem);
  }

  const date = config.filters.date;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onCancel}>
      <aside
        className="flex h-full w-full max-w-xl flex-col bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        aria-label="Panel editor"
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-800">
          <h2 className="font-semibold">{isNew ? "Add panel" : "Edit panel"}</h2>
          <button onClick={onCancel} className="text-gray-500 hover:text-current" aria-label="Close">✕</button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-4 text-sm">
          {/* Live preview */}
          <div className="h-56 rounded-lg border border-gray-200 p-2 dark:border-gray-800">
            {previewError ? (
              <p className="flex h-full items-center justify-center text-red-600">{previewError}</p>
            ) : (
              <PanelBody config={config} outcome={preview} loading={previewing} />
            )}
          </div>

          <Field label="Title">
            <input
              value={title}
              maxLength={MAX_TITLE}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Spend by category"
              className="w-full border p-1.5"
            />
          </Field>

          {/* "Show Me": the chart type. A div, not a <label>: a label would pass clicks in
              the gaps to the first button. */}
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Chart</span>
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
              {(Object.keys(catalogue.charts) as ChartType[]).map((chart) => (
                <button
                  key={chart}
                  onClick={() => pickChart(chart)}
                  aria-pressed={config.chart === chart}
                  className={`flex flex-col items-center gap-1 rounded-md border p-2 ${
                    config.chart === chart
                      ? "border-current font-medium"
                      : "border-gray-200 text-gray-500 hover:text-current dark:border-gray-800"
                  }`}
                >
                  <span aria-hidden className="font-mono text-xs">{CHART_ICONS[chart]}</span>
                  <span className="text-xs">{CHART_LABELS[chart]}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Shelves */}
          <div className="grid grid-cols-2 gap-3">
            {rules.x.length > 0 && (
              <Field label={config.chart === "pie" || config.chart === "donut" ? "Slices" : "X axis"}>
                <Select
                  value={config.x?.field ?? ""}
                  options={rules.x.map((d) => [d, DIMENSION_LABELS[d]])}
                  onChange={(field) => update({ x: { field: field as Dimension, granularity: config.x?.granularity } })}
                />
              </Field>
            )}
            {config.x?.field === "date" && (
              <Field label="Group dates by">
                <Select
                  value={config.x.granularity ?? "month"}
                  options={(catalogue.dimensions.find((d) => d.id === "date")?.granularities ?? []).map((g) => [g, GRANULARITY_LABELS[g]])}
                  onChange={(g) => update({ x: { field: "date", granularity: g as Granularity } })}
                />
              </Field>
            )}
            <Field label={config.chart === "histogram" ? "Values" : "Measure"}>
              <Select
                value={config.y.measure}
                options={measuresFor(config.chart, catalogue).map((m) => [m.id, MEASURE_LABELS[m.id]])}
                onChange={(m) => update({ y: { measure: m as Measure, agg: config.y.agg } })}
              />
            </Field>
            {config.chart !== "histogram" && measure && measure.aggs.length > 1 && (
              <Field label="Aggregation">
                <Select
                  value={config.y.agg}
                  options={measure.aggs.map((a) => [a, AGG_LABELS[a]])}
                  onChange={(agg) => update({ y: { ...config.y, agg: agg as Agg } })}
                />
              </Field>
            )}
            {rules.color && (
              <Field label="Colour (split into series)">
                <Select
                  value={config.color?.field ?? ""}
                  options={[
                    ["", "None"],
                    ...dimensions
                      .filter((d) => d !== "date" && d !== config.x?.field)
                      .map((d): [string, string] => [d, DIMENSION_LABELS[d]]),
                  ]}
                  onChange={(field) => update({ color: field ? { field: field as Dimension } : undefined })}
                />
              </Field>
            )}
          </div>

          {/* Options that only some charts have */}
          <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
            {categorical && config.chart !== "line" && config.chart !== "area" && (
              <>
                <Field label="Sort">
                  <Select
                    value={config.sort}
                    options={[["measure_desc", "Biggest first"], ["label", "A to Z"]]}
                    onChange={(sort) => update({ sort: sort as PanelConfig["sort"] })}
                  />
                </Field>
                <Field label={`Show top (${catalogue.limits.limit[0]}–${catalogue.limits.limit[1]})`}>
                  <input
                    type="number"
                    min={catalogue.limits.limit[0]}
                    max={catalogue.limits.limit[1]}
                    value={config.limit}
                    onChange={(e) => update({ limit: clamp(e.target.valueAsNumber, catalogue.limits.limit) })}
                    className="w-20 border p-1"
                  />
                </Field>
              </>
            )}
            {config.chart === "bar" && (
              <Field label="Bars">
                <Select
                  value={config.orientation}
                  options={[["vertical", "Vertical"], ["horizontal", "Horizontal"]]}
                  onChange={(o) => update({ orientation: o as PanelConfig["orientation"] })}
                />
              </Field>
            )}
            {config.chart === "bar" && config.color && (
              <Check label="Stack the colours" checked={config.stacked} onChange={(stacked) => update({ stacked })} />
            )}
            {config.chart === "histogram" && (
              <Field label={`Bins (${catalogue.limits.bins[0]}–${catalogue.limits.bins[1]})`}>
                <input
                  type="number"
                  min={catalogue.limits.bins[0]}
                  max={catalogue.limits.bins[1]}
                  value={config.bins}
                  onChange={(e) => update({ bins: clamp(e.target.valueAsNumber, catalogue.limits.bins) })}
                  className="w-20 border p-1"
                />
              </Field>
            )}
            {config.chart === "kpi" && (
              <Check
                label="Compare with the previous period"
                checked={config.compare}
                onChange={(compare) => update({ compare })}
              />
            )}
          </div>

          {/* This panel's own filters */}
          <fieldset className="space-y-3 rounded-lg border border-gray-200 p-3 dark:border-gray-800">
            <legend className="px-1 text-xs text-gray-500">Filters for this panel only</legend>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Date range">
                <Select
                  value={date.preset}
                  options={(["inherit", ...catalogue.date_presets] as (DatePreset | "inherit")[]).map((p) => [p, PRESET_LABELS[p]])}
                  onChange={(preset) =>
                    updateFilters({
                      date:
                        preset === "custom"
                          ? { preset: "custom", from: `${todayLocal().slice(0, 8)}01`, to: todayLocal() }
                          : { preset: preset as DatePreset | "inherit" },
                    })
                  }
                />
              </Field>
              {date.preset === "custom" && (
                <>
                  <Field label="From">
                    <input type="date" className="border p-1" value={date.from ?? ""} max={date.to}
                      onChange={(e) => e.target.value && updateFilters({ date: { ...date, from: e.target.value } })} />
                  </Field>
                  <Field label="To">
                    <input type="date" className="border p-1" value={date.to ?? ""} min={date.from}
                      onChange={(e) => e.target.value && updateFilters({ date: { ...date, to: e.target.value } })} />
                  </Field>
                </>
              )}
              <Field label="Money">
                <Select
                  value={config.filters.type ?? ""}
                  options={[["", "Same as dashboard"], ["debit", "Money out"], ["credit", "Money in"]]}
                  onChange={(type) => updateFilters({ type: (type || null) as PanelFilters["type"] })}
                />
              </Field>
              <CategoryPicker
                label="Categories"
                categories={categories}
                selected={config.filters.categories}
                onChange={(ids) => updateFilters({ categories: ids })}
              />
            </div>
            <Field label="Merchant name contains">
              <input
                value={config.filters.merchant_contains}
                maxLength={catalogue.limits.merchant_contains}
                onChange={(e) => updateFilters({ merchant_contains: e.target.value })}
                placeholder="e.g. cafe"
                className="w-full border p-1.5"
              />
            </Field>
          </fieldset>
        </div>

        <div className="flex items-center gap-3 border-t border-gray-200 px-4 py-3 dark:border-gray-800">
          <button
            onClick={save}
            disabled={saving}
            className="bg-black px-4 py-2 text-white disabled:opacity-50 dark:bg-white dark:text-black"
          >
            {saving ? "Saving…" : isNew ? "Add to dashboard" : "Save"}
          </button>
          <button onClick={onCancel} className="underline">Cancel</button>
          {error && <p className="text-red-600">{error}</p>}
        </div>
      </aside>
    </div>
  );
}

function clamp(value: number, [low, high]: [number, number]): number {
  return Number.isFinite(value) ? Math.min(Math.max(Math.round(value), low), high) : low;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-gray-500">{label}</span>
      {children}
    </label>
  );
}

function Select({
  value,
  options,
  onChange,
}: {
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <select className="border p-1" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(([id, label]) => (
        <option key={id} value={id}>{label}</option>
      ))}
    </select>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-2">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
