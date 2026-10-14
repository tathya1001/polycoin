"use client";

// The panel editor sheet: a chart-type picker plus "shelves" (x axis, measure, colour...).
//
// Pick a chart type, then fill its slots (x axis, measure, colour...) from dropdowns built
// from the backend's catalogue (GET /api/insights/fields/). Every change is passed through
// normalizeConfig, so the draft always obeys the chart rules, and a live preview re-queries
// the backend half a second after you stop changing things.

import { useEffect, useMemo, useState } from "react";
import {
  ChartArea,
  ChartColumn,
  ChartLine,
  ChartPie,
  Donut,
  Hash,
  BarChart3,
  X,
  type LucideIcon,
} from "lucide-react";
import PanelBody from "@/components/charts/PanelBody";
import { seriesSwatches } from "@/components/charts/toOption";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { isHexColor } from "@/lib/colors";
import { readError } from "@/lib/errors";
import {
  AGG_LABELS,
  CHART_LABELS,
  DIMENSION_LABELS,
  GRANULARITY_LABELS,
  MEASURE_LABELS,
  PRESET_LABELS,
  QUERY_URL,
  categoryColorMap,
  defaultConfig,
  isError,
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
import { Button, IconButton } from "@/components/ui/Button";
import { ColorPicker } from "@/components/ui/ColorPicker";
import { ErrorNote } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/Field";
import CategoryPicker from "./CategoryPicker";

const PREVIEW_DELAY_MS = 500; // the preview shares the 600/hour "insights" throttle
const MAX_TITLE = 80; // PanelUpdateSerializer.title max_length
const MAX_SERIES_COLORS = 50; // spec.MAX_SERIES_COLORS

const CHART_ICONS: Record<ChartType, LucideIcon> = {
  kpi: Hash,
  bar: ChartColumn,
  line: ChartLine,
  area: ChartArea,
  pie: ChartPie,
  donut: Donut,
  histogram: BarChart3,
};

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
  const categoryColors = useMemo(() => categoryColorMap(categories), [categories]);

  // The series the preview draws, each with its current colour: the Colors section below.
  const swatches = useMemo(
    () => (preview && !isError(preview) ? seriesSwatches(config, preview, categoryColors) : []),
    [config, preview, categoryColors],
  );

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

  // Set (or, with null, clear) one series colour override.
  function setSeriesColor(key: string, hex: string | null) {
    setConfig((current) => {
      const next = { ...current.series_colors };
      if (hex === null) delete next[key];
      else if (isHexColor(hex) && (key in next || Object.keys(next).length < MAX_SERIES_COLORS)) next[key] = hex;
      return { ...current, series_colors: next };
    });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  // Live preview, debounced: only the last change in a burst reaches the backend. Colour
  // overrides do not change the data, so they do not need the server: see the memo below.
  const dataKey = useMemo(() => JSON.stringify({ ...config, series_colors: undefined }), [config]);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      setPreviewing(true);
      try {
        const spec = JSON.parse(dataKey) as PanelConfig;
        const res = await apiFetch(QUERY_URL, {
          method: "POST",
          body: JSON.stringify({ filters: dashboardFilters, queries: [{ key: "preview", spec }] }),
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
  }, [dataKey, dashboardFilters]);

  async function save() {
    setSaving(true);
    setError(null);
    const problem = await onSave(title.trim(), config);
    setSaving(false);
    if (problem) setError(problem);
  }

  const date = config.filters.date;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/35" onClick={onCancel}>
      <aside
        className="flex h-full w-full max-w-5xl flex-col border-l-[1.5px] border-ink bg-canvas shadow-hard-lg"
        onClick={(e) => e.stopPropagation()}
        aria-label="Panel editor"
      >
        <div className="flex items-center justify-between border-b-[1.5px] border-ink bg-surface px-5 py-3">
          <h2 className="text-lg font-semibold tracking-tight">{isNew ? "Add panel" : "Edit panel"}</h2>
          <IconButton label="Close" icon={<X size={18} />} onClick={onCancel} />
        </div>

        <div className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-5 lg:grid-cols-[1fr_minmax(0,1.1fr)] lg:overflow-hidden">
          {/* Live preview: first on phones, sticky on the right on wide screens */}
          <div className="lg:order-2 lg:flex lg:flex-col">
            <div className="h-72 rounded-md border-[1.5px] border-ink bg-surface p-2 shadow-hard-sm lg:h-auto lg:flex-1">
              {previewError ? (
                <p className="flex h-full items-center justify-center font-medium text-neg">{previewError}</p>
              ) : (
                <PanelBody config={config} outcome={preview} loading={previewing} categoryColors={categoryColors} />
              )}
            </div>
          </div>

          <div className="space-y-6 lg:order-1 lg:overflow-y-auto lg:pr-1">
            <Field label="Title">
              <Input
                value={title}
                maxLength={MAX_TITLE}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Spend by category"
              />
            </Field>

            {/* "Show Me": the chart type. A div, not a <label>: a label would pass clicks in
                the gaps to the first button. */}
            <Section title="Chart">
              <div className="grid grid-cols-4 gap-2 sm:grid-cols-7 lg:grid-cols-4 xl:grid-cols-7">
                {(Object.keys(catalogue.charts) as ChartType[]).map((chart) => {
                  const Icon = CHART_ICONS[chart];
                  const on = config.chart === chart;
                  return (
                    <button
                      key={chart}
                      type="button"
                      onClick={() => pickChart(chart)}
                      aria-pressed={on}
                      className={cn(
                        "flex flex-col items-center gap-1 rounded-md border-[1.5px] p-2 text-xs font-medium transition-[transform,background-color] duration-150",
                        on
                          ? "border-ink bg-ink text-white"
                          : "border-ink/25 bg-surface text-ink-2 hover:border-ink hover:text-ink",
                      )}
                    >
                      <Icon size={20} strokeWidth={1.75} aria-hidden />
                      {CHART_LABELS[chart]}
                    </button>
                  );
                })}
              </div>
            </Section>

            {/* Shelves */}
            <Section title="Data">
              <div className="grid grid-cols-2 gap-3">
                {rules.x.length > 0 && (
                  <Field label={config.chart === "pie" || config.chart === "donut" ? "Slices" : "X axis"}>
                    <Select
                      dense
                      className="w-full"
                      value={config.x?.field ?? ""}
                      onChange={(e) =>
                        update({ x: { field: e.target.value as Dimension, granularity: config.x?.granularity } })
                      }
                    >
                      {rules.x.map((d) => (
                        <option key={d} value={d}>
                          {DIMENSION_LABELS[d]}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                {config.x?.field === "date" && (
                  <Field label="Group dates by">
                    <Select
                      dense
                      className="w-full"
                      value={config.x.granularity ?? "month"}
                      onChange={(e) => update({ x: { field: "date", granularity: e.target.value as Granularity } })}
                    >
                      {(catalogue.dimensions.find((d) => d.id === "date")?.granularities ?? []).map((g) => (
                        <option key={g} value={g}>
                          {GRANULARITY_LABELS[g]}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                <Field label={config.chart === "histogram" ? "Values" : "Measure"}>
                  <Select
                    dense
                    className="w-full"
                    value={config.y.measure}
                    onChange={(e) => update({ y: { measure: e.target.value as Measure, agg: config.y.agg } })}
                  >
                    {measuresFor(config.chart, catalogue).map((m) => (
                      <option key={m.id} value={m.id}>
                        {MEASURE_LABELS[m.id]}
                      </option>
                    ))}
                  </Select>
                </Field>
                {config.chart !== "histogram" && measure && measure.aggs.length > 1 && (
                  <Field label="Aggregation">
                    <Select
                      dense
                      className="w-full"
                      value={config.y.agg}
                      onChange={(e) => update({ y: { ...config.y, agg: e.target.value as Agg } })}
                    >
                      {measure.aggs.map((a) => (
                        <option key={a} value={a}>
                          {AGG_LABELS[a]}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                {rules.color && (
                  <Field label="Colour (split into series)">
                    <Select
                      dense
                      className="w-full"
                      value={config.color?.field ?? ""}
                      onChange={(e) => update({ color: e.target.value ? { field: e.target.value as Dimension } : undefined })}
                    >
                      <option value="">None</option>
                      {dimensions
                        .filter((d) => d !== "date" && d !== config.x?.field)
                        .map((d) => (
                          <option key={d} value={d}>
                            {DIMENSION_LABELS[d]}
                          </option>
                        ))}
                    </Select>
                  </Field>
                )}
              </div>
            </Section>

            {/* Options that only some charts have */}
            <Section title="Options">
              <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
                {categorical && config.chart !== "line" && config.chart !== "area" && (
                  <>
                    <Field label="Sort" className="w-40">
                      <Select
                        dense
                        className="w-full"
                        value={config.sort}
                        onChange={(e) => update({ sort: e.target.value as PanelConfig["sort"] })}
                      >
                        <option value="measure_desc">Biggest first</option>
                        <option value="label">A to Z</option>
                      </Select>
                    </Field>
                    <Field label={`Show top (${catalogue.limits.limit[0]}–${catalogue.limits.limit[1]})`} className="w-32">
                      <Input
                        dense
                        type="number"
                        min={catalogue.limits.limit[0]}
                        max={catalogue.limits.limit[1]}
                        value={config.limit}
                        onChange={(e) => update({ limit: clamp(e.target.valueAsNumber, catalogue.limits.limit) })}
                      />
                    </Field>
                  </>
                )}
                {config.chart === "bar" && (
                  <Field label="Bars" className="w-36">
                    <Select
                      dense
                      className="w-full"
                      value={config.orientation}
                      onChange={(e) => update({ orientation: e.target.value as PanelConfig["orientation"] })}
                    >
                      <option value="vertical">Vertical</option>
                      <option value="horizontal">Horizontal</option>
                    </Select>
                  </Field>
                )}
                {config.chart === "bar" && config.color && (
                  <Checkbox label="Stack the colours" checked={config.stacked} onChange={(stacked) => update({ stacked })} />
                )}
                {config.chart === "histogram" && (
                  <Field label={`Bins (${catalogue.limits.bins[0]}–${catalogue.limits.bins[1]})`} className="w-32">
                    <Input
                      dense
                      type="number"
                      min={catalogue.limits.bins[0]}
                      max={catalogue.limits.bins[1]}
                      value={config.bins}
                      onChange={(e) => update({ bins: clamp(e.target.valueAsNumber, catalogue.limits.bins) })}
                    />
                  </Field>
                )}
                {config.chart === "kpi" && (
                  <Checkbox
                    label="Compare with the previous period"
                    checked={config.compare}
                    onChange={(compare) => update({ compare })}
                  />
                )}
              </div>
            </Section>

            {/* Colours: category colours are the default; any series can be overridden here. */}
            {swatches.length > 0 && (
              <Section title="Colours">
                <p className="mb-2 text-xs text-muted">
                  Category colours come from the Categories page. Pick a colour here to change it for this chart only.
                </p>
                <ul className="grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
                  {swatches.map((swatch) => {
                    const overridden = swatch.key in config.series_colors;
                    return (
                      <li key={swatch.key} className="flex items-center gap-2.5">
                        <ColorPicker
                          value={swatch.color}
                          label={`Colour for ${swatch.label}`}
                          onChange={(hex) => setSeriesColor(swatch.key, hex)}
                          onReset={overridden ? () => setSeriesColor(swatch.key, null) : undefined}
                          resetLabel="Use the default colour"
                        />
                        <span className="min-w-0 flex-1 truncate text-sm">{swatch.label}</span>
                        {overridden && <span className="text-xs text-muted">custom</span>}
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            {/* This panel's own filters */}
            <Section title="Filters for this panel only">
              <div className="space-y-3">
                <div className="flex flex-wrap items-end gap-3">
                  <Field label="Date range" className="w-48">
                    <Select
                      dense
                      className="w-full"
                      value={date.preset}
                      onChange={(e) => {
                        const preset = e.target.value as DatePreset | "inherit";
                        updateFilters({
                          date:
                            preset === "custom"
                              ? { preset: "custom", from: `${todayLocal().slice(0, 8)}01`, to: todayLocal() }
                              : { preset },
                        });
                      }}
                    >
                      {(["inherit", ...catalogue.date_presets] as (DatePreset | "inherit")[]).map((p) => (
                        <option key={p} value={p}>
                          {PRESET_LABELS[p]}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {date.preset === "custom" && (
                    <>
                      <Field label="From" className="w-40">
                        <Input
                          dense
                          type="date"
                          value={date.from ?? ""}
                          max={date.to}
                          onChange={(e) => e.target.value && updateFilters({ date: { ...date, from: e.target.value } })}
                        />
                      </Field>
                      <Field label="To" className="w-40">
                        <Input
                          dense
                          type="date"
                          value={date.to ?? ""}
                          min={date.from}
                          onChange={(e) => e.target.value && updateFilters({ date: { ...date, to: e.target.value } })}
                        />
                      </Field>
                    </>
                  )}
                  <Field label="Money" className="w-44">
                    <Select
                      dense
                      className="w-full"
                      value={config.filters.type ?? ""}
                      onChange={(e) => updateFilters({ type: (e.target.value || null) as PanelFilters["type"] })}
                    >
                      <option value="">Same as dashboard</option>
                      <option value="debit">Money out</option>
                      <option value="credit">Money in</option>
                    </Select>
                  </Field>
                  <div className="space-y-1.5">
                    <span className="block text-[13px] font-medium">Categories</span>
                    <CategoryPicker
                      label="Categories"
                      categories={categories}
                      selected={config.filters.categories}
                      onChange={(ids) => updateFilters({ categories: ids })}
                    />
                  </div>
                </div>
                <Field label="Merchant name contains">
                  <Input
                    dense
                    value={config.filters.merchant_contains}
                    maxLength={catalogue.limits.merchant_contains}
                    onChange={(e) => updateFilters({ merchant_contains: e.target.value })}
                    placeholder="e.g. cafe"
                  />
                </Field>
              </div>
            </Section>
          </div>
        </div>

        <div className="flex items-center gap-3 border-t-[1.5px] border-ink bg-surface px-5 py-3">
          <Button variant="primary" loading={saving} onClick={save}>
            {saving ? "Saving…" : isNew ? "Add to dashboard" : "Save"}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          {error && <ErrorNote className="ml-auto">{error}</ErrorNote>}
        </div>
      </aside>
    </div>
  );
}

function clamp(value: number, [low, high]: [number, number]): number {
  return Number.isFinite(value) ? Math.min(Math.max(Math.round(value), low), high) : low;
}

// A titled group of controls on a white card.
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold tracking-wider text-ink-2 uppercase">{title}</h3>
      {children}
    </section>
  );
}
