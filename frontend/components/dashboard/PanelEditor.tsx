"use client";

// The panel editor sheet: a chart-type picker plus "shelves" (x axis, measure, colour...).
//
// Pick a chart type, then fill its slots (x axis, measure, colour...) from dropdowns built
// from the backend's catalogue (GET /api/insights/fields/). Every change is passed through
// normalizeConfig, so the draft always obeys the chart rules, and a live preview re-queries
// the backend half a second after you stop changing things.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CalendarDays,
  ChartArea,
  ChartColumn,
  ChartLine,
  ChartPie,
  Donut,
  Grid3x3,
  Hash,
  BarChart3,
  Type,
  X,
  type LucideIcon,
} from "lucide-react";
import PanelBody from "@/components/charts/PanelBody";
import { useSession } from "@/components/shell/Session";
import { seriesSwatches } from "@/components/charts/toOption";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { isHexColor } from "@/lib/colors";
import { readError } from "@/lib/errors";
import {
  AGG_LABELS,
  BIND_FIELDS,
  BIND_LABELS,
  CALC_LABELS,
  CHANGE_AS_LABELS,
  CHANGE_VS_LABELS,
  CHART_LABELS,
  DEFAULT_FORMULA,
  DIMENSION_LABELS,
  FORMULA_EXAMPLES,
  FORMULA_FORM_LABELS,
  FORMULA_GROUP_LABELS,
  GRANULARITY_LABELS,
  KPI_COMPARE_LABELS,
  KPI_DIRECTION_LABELS,
  KPI_FIGURE_LABELS,
  LEGEND_LABELS,
  MEASURE_LABELS,
  NUMBER_FORMAT_LABELS,
  PRESET_LABELS,
  GROUPED_CHARTS,
  QUERY_URL,
  bindingAllowed,
  calcAllowed,
  categoryColorMap,
  defaultConfig,
  defaultFormat,
  defaultKpi,
  figureAllowed,
  formulaAllowed,
  insertAt,
  isError,
  measuresFor,
  normalizeConfig,
  todayLocal,
} from "@/lib/insights";
import { sourceRef } from "@/lib/dataSources";
import { CHART_LOOKS } from "@/lib/theme";
import { isText } from "@/lib/types";
import type {
  Agg,
  AnyPanelConfig,
  Bindings,
  DashboardParameters,
  CalcType,
  Catalogue,
  Category,
  ChartType,
  DataSource,
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
  Measure,
  PanelConfig,
  PanelFilters,
  QueryOutcome,
  TableCalc,
  TextConfig,
} from "@/lib/types";
import { Button, IconButton } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Card";
import { ColorPicker } from "@/components/ui/ColorPicker";
import { ErrorNote } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/Field";
import CategoryPicker from "./CategoryPicker";
import SourcePicker from "./SourcePicker";

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
  calendar: CalendarDays,
  heatmap: Grid3x3,
  text: Type,
};

type Props = {
  catalogue: Catalogue;
  categories: Category[];
  sources: DataSource[];
  parameters: DashboardParameters; // the dashboard's current values, for the live preview
  initial: { title: string; showTitle: boolean; config: AnyPanelConfig };
  isNew: boolean;
  dashboardFilters: PanelFilters;
  onCancel: () => void;
  onSave: (title: string, showTitle: boolean, config: AnyPanelConfig) => Promise<string | null>; // error, or null
};

export default function PanelEditor(props: Props) {
  const { catalogue, categories, sources, parameters, initial, isNew, dashboardFilters, onCancel, onSave } = props;
  const { theme } = useSession();
  const [title, setTitle] = useState(initial.title);
  const [showTitle, setShowTitle] = useState(initial.showTitle);
  // A note and a chart are different shapes. The chart draft is always a valid chart (so the
  // chart controls never see a note), and `textMode` says which of the two this panel is.
  const [textMode, setTextMode] = useState(isText(initial.config));
  const [note, setNote] = useState(isText(initial.config) ? initial.config.text : "");
  const [config, setConfig] = useState(() =>
    normalizeConfig(isText(initial.config) ? defaultConfig("bar") : initial.config, catalogue),
  );
  const [preview, setPreview] = useState<QueryOutcome | undefined>(undefined);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rules = catalogue.charts[config.chart];
  const measure = catalogue.measures.find((m) => m.id === config.y.measure);
  const categorical = !!config.x && config.x.field !== "date";
  const dimensions = catalogue.dimensions.map((d) => d.id);
  const categoryColors = useMemo(() => categoryColorMap(categories, sources), [categories, sources]);

  // The series the preview draws, each with its current colour: the Colors section below.
  const swatches = useMemo(
    () => (preview && !isError(preview) ? seriesSwatches(config, preview, categoryColors, CHART_LOOKS[theme]) : []),
    [config, preview, categoryColors, theme],
  );

  function update(change: Partial<PanelConfig>) {
    setConfig((current) => normalizeConfig({ ...current, ...change }, catalogue));
  }

  function updateFilters(change: Partial<PanelFilters>) {
    setConfig((current) => ({ ...current, filters: { ...current.filters, ...change } }));
  }

  function pickChart(chart: ChartType) {
    setTextMode(chart === "text");
    if (chart === "text") return;
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
    if (textMode) return; // a note has nothing to query
    let cancelled = false;
    const timer = setTimeout(async () => {
      setPreviewing(true);
      try {
        const spec = JSON.parse(dataKey) as PanelConfig;
        const res = await apiFetch(QUERY_URL, {
          method: "POST",
          body: JSON.stringify({ filters: dashboardFilters, parameters, queries: [{ key: "preview", spec }] }),
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
  }, [dataKey, dashboardFilters, parameters, textMode]);

  async function save() {
    setSaving(true);
    setError(null);
    const problem = await onSave(title.trim(), showTitle, textMode ? noteConfig : config);
    setSaving(false);
    if (problem) setError(problem);
  }

  const date = config.filters.date;
  const noteConfig: TextConfig = { v: catalogue.version, chart: "text", text: note };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/35" onClick={onCancel}>
      <aside
        className="flex h-full w-full max-w-5xl flex-col border-l-[1.5px] border-line bg-canvas shadow-overlay"
        onClick={(e) => e.stopPropagation()}
        aria-label="Panel editor"
      >
        <div className="flex items-center justify-between border-b-[1.5px] border-line bg-surface px-5 py-3">
          <h2 className="text-lg font-semibold tracking-tight">{isNew ? "Add panel" : "Edit panel"}</h2>
          <IconButton label="Close" icon={<X size={18} />} onClick={onCancel} />
        </div>

        <div className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-5 lg:grid-cols-[1fr_minmax(0,1.1fr)] lg:overflow-hidden">
          {/* Live preview: first on phones, sticky on the right on wide screens */}
          <div className="lg:order-2 lg:flex lg:flex-col">
            <div className="h-72 rounded-md border-[1.5px] border-line bg-canvas p-2 lg:h-auto lg:flex-1">
              {previewError && !textMode ? (
                <p className="flex h-full items-center justify-center font-medium text-neg">{previewError}</p>
              ) : (
                <PanelBody
                  config={textMode ? noteConfig : config}
                  outcome={preview}
                  loading={previewing}
                  categoryColors={categoryColors}
                />
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
            <Checkbox
              label="Show the title on the dashboard"
              checked={showTitle}
              onChange={setShowTitle}
              className="-mt-3"
            />

            {/* "Show Me": the chart type. A div, not a <label>: a label would pass clicks in
                the gaps to the first button. */}
            <Section title="Chart">
              <div className="grid grid-cols-4 gap-2 sm:grid-cols-7 lg:grid-cols-4 xl:grid-cols-7">
                {(Object.keys(catalogue.charts) as ChartType[]).map((chart) => {
                  const Icon = CHART_ICONS[chart];
                  const on = textMode ? chart === "text" : config.chart === chart;
                  return (
                    <button
                      key={chart}
                      type="button"
                      onClick={() => pickChart(chart)}
                      aria-pressed={on}
                      className={cn(
                        "flex flex-col items-center gap-1 rounded-md border-[1.5px] p-2 text-xs font-medium transition-[transform,background-color] duration-150",
                        on
                          ? "border-fill bg-fill text-on-fill"
                          : "border-line bg-surface text-ink-2 hover:border-edge hover:text-ink",
                      )}
                    >
                      <Icon size={20} strokeWidth={1.75} aria-hidden />
                      {CHART_LABELS[chart]}
                    </button>
                  );
                })}
              </div>
            </Section>

            {!textMode && (
              <>
                {/* Shelves */}
                <Section title="Data">
                  <div className="grid grid-cols-2 gap-3">
                    {rules.x.length > 0 && (
                      <Field label={xLabel(config.chart)}>
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
                    {config.chart === "heatmap" && (
                      <Field label="Rows">
                        <Select
                          dense
                          className="w-full"
                          value={config.rows?.field ?? ""}
                          onChange={(e) => update({ rows: { field: e.target.value as Dimension } })}
                        >
                          {catalogue.rows_fields
                            .filter((field) => field !== config.x?.field)
                            .map((field) => (
                              <option key={field} value={field}>
                                {DIMENSION_LABELS[field]}
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
                        {formulaAllowed(config.chart, catalogue) && (
                          <option value="formula">{MEASURE_LABELS.formula}…</option>
                        )}
                      </Select>
                    </Field>
                    {config.y.measure === "formula" && (
                      <FormulaFields
                        config={config}
                        catalogue={catalogue}
                        sources={sources}
                        onChange={(formula) => update({ y: { ...config.y, formula } })}
                      />
                    )}
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
                    {GROUPED_CHARTS.includes(config.chart) && (
                      <CalcFields
                        config={config}
                        catalogue={catalogue}
                        onChange={(calc) => update({ calc })}
                      />
                    )}
                    {(categorical || config.chart === "heatmap") && config.chart !== "line" && config.chart !== "area" && (
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
                      <KpiFields config={config} catalogue={catalogue} onChange={(kpi) => update({ kpi })} />
                    )}
                  </div>
                </Section>

                {/* Which fields follow a dashboard parameter */}
            {BIND_FIELDS.some((field) => bindingAllowed(config, field)) && (
              <Section title="Dashboard parameters">
                <BindFields config={config} catalogue={catalogue} onChange={(bind) => update({ bind })} />
              </Section>
            )}

            {/* Labels, number style, legend and axis bounds */}
                {catalogue.format.charts.includes(config.chart) && (
                  <Section title="Labels and formatting">
                    <FormatFields
                      config={config}
                      catalogue={catalogue}
                      onChange={(format) => update({ format })}
                    />
                  </Section>
                )}

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
                      <div className="space-y-1.5">
                        {sources.length > 1 && <span className="block text-[13px] font-medium">Data sources</span>}
                        <SourcePicker
                          sources={sources}
                          selected={config.filters.data_sources}
                          allLabel="Same as dashboard"
                          onChange={(ids) => updateFilters({ data_sources: ids })}
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
              </>
            )}

            {textMode && (
              <Section title="Text">
                <Field
                  label={`Words (up to ${catalogue.limits.text} characters)`}
                  hint="# Heading, ## Smaller heading, - a bullet, **bold**, *italic*, `code`. Nothing else is interpreted."
                >
                  <Textarea
                    rows={9}
                    value={note}
                    maxLength={catalogue.limits.text}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="e.g. ## Budget notes&#10;Keep food under ₹10,000."
                  />
                </Field>
              </Section>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 border-t-[1.5px] border-line bg-surface px-5 py-3">
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

// What the first axis is called, by chart: slices, columns of a matrix, or the x axis.
function xLabel(chart: PanelConfig["chart"]): string {
  if (chart === "pie" || chart === "donut") return "Slices";
  return chart === "heatmap" ? "Columns" : "X axis";
}

function clamp(value: number, [low, high]: [number, number]): number {
  return Number.isFinite(value) ? Math.min(Math.max(Math.round(value), low), high) : low;
}

// A calculated field: the formula and how its result reads. The server checks the formula and
// the live preview shows its message, so the rules live in one place (spec.validate_formula).
// The reference list comes from the catalogue; picking an entry types it at the cursor.
function FormulaFields({
  config,
  catalogue,
  sources,
  onChange,
}: {
  config: PanelConfig;
  catalogue: Catalogue;
  sources: DataSource[];
  onChange: (formula: Formula) => void;
}) {
  const formula = config.y.formula ?? DEFAULT_FORMULA;
  const rules = catalogue.formula;
  const box = useRef<HTMLTextAreaElement>(null);
  const cursor = useRef<number | null>(null);

  // After an insert has re-rendered the text, put the cursor where the insert left it.
  useEffect(() => {
    if (cursor.current === null || !box.current) return;
    box.current.focus();
    box.current.setSelectionRange(cursor.current, cursor.current);
    cursor.current = null;
  });

  function insert(before: string, after = "") {
    const start = box.current?.selectionStart ?? formula.expression.length;
    const end = box.current?.selectionEnd ?? start;
    const next = insertAt(formula.expression, start, end, before, after);
    if (next.text.length > rules.max_length) return;
    cursor.current = next.cursor;
    onChange({ ...formula, expression: next.text });
  }

  const groups = (Object.keys(FORMULA_GROUP_LABELS) as FormulaFunctionGroup[]).map((group) => ({
    title: FORMULA_GROUP_LABELS[group],
    items: rules.functions
      .filter((fn) => fn.group === group)
      .map((fn) => ({
        label: fn.signature,
        help: fn.help,
        before: fn.name === "DATE" ? 'DATE("' : `${fn.name}(`,
        after: fn.name === "DATE" ? '")' : ")",
      })),
  }));

  return (
    <div className="col-span-2 space-y-3">
      <Field
        label="Formula"
        hint={
          <>
            Totals for each group: {rules.variables.map((v) => v.name).join(", ")}. Fields hold one value per
            transaction: write them in brackets, such as [Category], inside SUM(), COUNT()… A division by zero
            leaves that point empty.
          </>
        }
      >
        <Textarea
          ref={box}
          className="min-h-16 font-mono"
          value={formula.expression}
          maxLength={rules.max_length}
          spellCheck={false}
          onChange={(e) => onChange({ ...formula, expression: e.target.value })}
          placeholder={DEFAULT_FORMULA.expression}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-2">Examples:</span>
        {FORMULA_EXAMPLES.map((example) => (
          <Chip
            key={example.label}
            active={formula.expression === example.formula.expression}
            onClick={() => onChange(example.formula)}
          >
            {example.label}
          </Chip>
        ))}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-ink-2">Fields and functions</summary>
        <div className="mt-2 max-h-72 space-y-3 overflow-y-auto pr-1">
          <FormulaReference
            title="Totals"
            items={rules.variables.map((v) => ({ label: v.name, help: v.help, before: v.name }))}
            onPick={insert}
          />
          <FormulaReference
            title="Fields"
            items={rules.fields.map((f) => ({ label: `[${f.name}]`, help: f.help, before: `[${f.name}]` }))}
            onPick={insert}
          />
          <FormulaReference
            title="Data sources"
            items={sources.map((source) => ({
              label: `${sourceRef(source.name, rules.keywords)}.spend`,
              help: `Reads ${source.name} whatever the panel shows. Also .income, .net, .count, .balance, or .SUM(…).`,
              before: `${sourceRef(source.name, rules.keywords)}.spend`,
            }))}
            onPick={insert}
          />
          {groups.map((group) => (
            <FormulaReference key={group.title} {...group} onPick={insert} />
          ))}
          <p className="text-xs text-ink-2">
            Also: IF … THEN … ELSEIF … ELSE … END, CASE WHEN … THEN … ELSE … END, AND, OR, NOT, IN (…), the
            comparisons = &lt;&gt; &lt; &lt;= &gt; &gt;=, and text in quotes. Text matches ignore letter case.
          </p>
        </div>
      </details>
      <Field label="Show the result as" className="w-48">
        <Select
          dense
          className="w-full"
          value={formula.as}
          onChange={(e) => onChange({ ...formula, as: e.target.value as FormulaForm })}
        >
          {rules.forms.map((form) => (
            <option key={form} value={form}>
              {FORMULA_FORM_LABELS[form]}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}

// One group of the formula reference. Picking an entry types `before` + `after` at the cursor.
function FormulaReference({
  title,
  items,
  onPick,
}: {
  title: string;
  items: { label: string; help: string; before: string; after?: string }[];
  onPick: (before: string, after?: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-semibold">{title}</p>
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.label}>
            <button
              type="button"
              onClick={() => onPick(item.before, item.after)}
              className="w-full rounded-sm px-1.5 py-1 text-left transition-colors duration-150 hover:bg-wash"
            >
              <span className="font-mono text-[13px]">{item.label}</span>{" "}
              <span className="text-xs text-ink-2">{item.help}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// The table calculation picker. Options the draft can't use stay visible but disabled, and the
// hint says why, so the rule is learnable rather than hidden.
function CalcFields({
  config,
  catalogue,
  onChange,
}: {
  config: PanelConfig;
  catalogue: Catalogue;
  onChange: (calc: TableCalc | undefined) => void;
}) {
  const calc = config.calc;
  const needsDate = config.x?.field !== "date";
  const [low, high] = catalogue.limits.window;
  return (
    <>
      <Field
        label="Calculation"
        className="w-44"
        hint={needsDate ? "Running total, moving average and change need dates on the x axis." : undefined}
      >
        <Select
          dense
          className="w-full"
          value={calc?.type ?? ""}
          onChange={(e) => onChange(e.target.value ? { type: e.target.value as CalcType } : undefined)}
        >
          <option value="">None</option>
          {catalogue.calcs.map((c) => (
            <option key={c.id} value={c.id} disabled={!calcAllowed(config, catalogue, c.id)}>
              {CALC_LABELS[c.id]}
            </option>
          ))}
        </Select>
      </Field>
      {calc?.type === "moving_average" && (
        <Field label={`Over (${low}–${high} periods)`} className="w-36">
          <Input
            dense
            type="number"
            min={low}
            max={high}
            value={calc.window ?? 3}
            onChange={(e) => onChange({ ...calc, window: clamp(e.target.valueAsNumber, [low, high]) })}
          />
        </Field>
      )}
      {calc?.type === "change" && (
        <>
          <Field label="Compared with" className="w-56">
            <Select
              dense
              className="w-full"
              value={calc.vs ?? "previous"}
              onChange={(e) => onChange({ ...calc, vs: e.target.value as TableCalc["vs"] })}
            >
              {catalogue.change_vs.map((vs) => (
                <option key={vs} value={vs}>
                  {CHANGE_VS_LABELS[vs]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Shown as" className="w-32">
            <Select
              dense
              className="w-full"
              value={calc.as ?? "percent"}
              onChange={(e) => onChange({ ...calc, as: e.target.value as TableCalc["as"] })}
            >
              {catalogue.change_as.map((as) => (
                <option key={as} value={as}>
                  {CHANGE_AS_LABELS[as]}
                </option>
              ))}
            </Select>
          </Field>
        </>
      )}
    </>
  );
}

// The KPI card's options. Figures the draft can't show stay visible but disabled.
function KpiFields({
  config,
  catalogue,
  onChange,
}: {
  config: PanelConfig;
  catalogue: Catalogue;
  onChange: (kpi: KpiOptions) => void;
}) {
  const kpi = config.kpi ?? defaultKpi();
  const [low, high] = catalogue.kpi.average_of;
  const date = catalogue.dimensions.find((d) => d.id === "date");
  const full = kpi.secondary.length >= catalogue.kpi.max_secondary;

  function toggle(figure: KpiFigure, on: boolean) {
    onChange({ ...kpi, secondary: on ? [...kpi.secondary, figure] : kpi.secondary.filter((f) => f !== figure) });
  }

  return (
    <>
      <Field label="Compare with" className="w-64">
        <Select
          dense
          className="w-full"
          value={kpi.compare}
          onChange={(e) => onChange({ ...kpi, compare: e.target.value as KpiCompare })}
        >
          {catalogue.kpi.compares.map((compare) => (
            <option key={compare} value={compare}>
              {KPI_COMPARE_LABELS[compare]}
            </option>
          ))}
        </Select>
      </Field>
      {kpi.compare === "average" && (
        <Field label={`Over (${low}–${high} periods)`} className="w-36">
          <Input
            dense
            type="number"
            min={low}
            max={high}
            value={kpi.average_of ?? 3}
            onChange={(e) => onChange({ ...kpi, average_of: clamp(e.target.valueAsNumber, [low, high]) })}
          />
        </Field>
      )}
      {kpi.compare !== "none" && (
        <Field label="A rise is" className="w-72">
          <Select
            dense
            className="w-full"
            value={kpi.direction}
            onChange={(e) => onChange({ ...kpi, direction: e.target.value as KpiDirection })}
          >
            {catalogue.kpi.directions.map((direction) => (
              <option key={direction} value={direction}>
                {KPI_DIRECTION_LABELS[direction]}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field label="Trend line" className="w-40">
        <Select
          dense
          className="w-full"
          value={kpi.sparkline ?? ""}
          onChange={(e) => onChange({ ...kpi, sparkline: (e.target.value || null) as KpiOptions["sparkline"] })}
        >
          <option value="">None</option>
          {(date?.granularities ?? []).map((step) => (
            <option key={step} value={step}>
              By {GRANULARITY_LABELS[step].toLowerCase()}
            </option>
          ))}
        </Select>
      </Field>
      <fieldset className="w-full">
        <legend className="mb-1.5 text-[13px] font-medium">
          Small figures (up to {catalogue.kpi.max_secondary})
        </legend>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {catalogue.kpi.secondary.map(({ id }) => (
            <Checkbox
              key={id}
              label={KPI_FIGURE_LABELS[id]}
              checked={kpi.secondary.includes(id)}
              disabled={!figureAllowed(config, catalogue, id) || (full && !kpi.secondary.includes(id))}
              onChange={(on) => toggle(id, on)}
            />
          ))}
        </div>
      </fieldset>
    </>
  );
}

// Switches for the fields of this panel that can follow a dashboard parameter. A bound field takes
// the parameter's value instead of its own; the control for it shows above the charts.
function BindFields({
  config,
  catalogue,
  onChange,
}: {
  config: PanelConfig;
  catalogue: Catalogue;
  onChange: (bind: Bindings) => void;
}) {
  const bind = config.bind ?? {};
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        A bound field follows the control above the dashboard&apos;s charts instead of the value set here.
      </p>
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        {BIND_FIELDS.filter((field) => bindingAllowed(config, field)).map((field) => (
          <Checkbox
            key={field}
            label={BIND_LABELS[field]}
            checked={!!bind[field]}
            onChange={(on) => {
              const next = { ...bind };
              if (on) next[field] = catalogue.parameters.bindings[field];
              else delete next[field];
              onChange(next);
            }}
          />
        ))}
      </div>
    </div>
  );
}

// Labels, number style, legend and value-axis bounds. Options a chart doesn't have are left out.
function FormatFields({
  config,
  catalogue,
  onChange,
}: {
  config: PanelConfig;
  catalogue: Catalogue;
  onChange: (format: FormatOptions) => void;
}) {
  const format = config.format ?? defaultFormat();
  const hasLegend = catalogue.format.legend_charts.includes(config.chart);
  const hasAxis = catalogue.format.axis_charts.includes(config.chart);
  const { min, max } = format.axis;
  const backwards = min !== null && max !== null && min >= max;

  // An emptied box is "automatic" (no bound), not zero.
  const bound = (which: "min" | "max", value: number) =>
    onChange({ ...format, axis: { ...format.axis, [which]: Number.isFinite(value) ? value : null } });

  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
      <Checkbox
        label="Show values on the chart"
        checked={format.labels}
        onChange={(labels) => onChange({ ...format, labels })}
      />
      <Field label="Numbers" className="w-72">
        <Select
          dense
          className="w-full"
          value={format.number}
          onChange={(e) => onChange({ ...format, number: e.target.value as FormatOptions["number"] })}
        >
          {catalogue.format.numbers.map((style) => (
            <option key={style} value={style}>
              {NUMBER_FORMAT_LABELS[style]}
            </option>
          ))}
        </Select>
      </Field>
      {hasLegend && (
        <Field label="Legend" className="w-36">
          <Select
            dense
            className="w-full"
            value={format.legend}
            onChange={(e) => onChange({ ...format, legend: e.target.value as FormatOptions["legend"] })}
          >
            {catalogue.format.legends.map((position) => (
              <option key={position} value={position}>
                {LEGEND_LABELS[position]}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {hasAxis && (
        <>
          <Field label="Axis starts at" className="w-36" error={backwards ? "Start must be below the end." : null}>
            <Input
              dense
              type="number"
              value={min ?? ""}
              placeholder="Automatic"
              onChange={(e) => bound("min", e.target.valueAsNumber)}
            />
          </Field>
          <Field label="Axis ends at" className="w-36">
            <Input
              dense
              type="number"
              value={max ?? ""}
              placeholder="Automatic"
              onChange={(e) => bound("max", e.target.valueAsNumber)}
            />
          </Field>
        </>
      )}
    </div>
  );
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
