"use client";

// The Insights dashboard: tabs of user-built dashboards, each a grid of chart panels.
//
// Data flow:
//   - GET  /api/dashboards/        the tabs
//   - GET  /api/dashboards/{id}/   the active tab's panels (decrypted titles and configs)
//   - POST /api/insights/query/    every panel's chart data in ONE request, so the server
//                                  decrypts the user's transactions once, not once per panel
//   - POST /api/insights/rows/     the transactions behind a clicked mark, only when asked for
//   - PUT  /api/dashboards/{id}/layout/   panel positions, saved after a drag or resize
//
// Every insights call shares a 600/hour budget, so queries only re-run when a panel's
// config or the filters really change (not when panels move), and layout saves are batched.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Check,
  ExternalLink,
  Filter,
  FilterX,
  LayoutDashboard,
  List,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import AgentDialog from "@/components/agent/AgentDialog";
import DashboardGrid from "@/components/dashboard/DashboardGrid";
import DashboardTabs from "@/components/dashboard/DashboardTabs";
import FilterBar from "@/components/dashboard/FilterBar";
import type { MarkAction } from "@/components/dashboard/MarkMenu";
import ParameterBar from "@/components/dashboard/ParameterBar";
import PanelEditor from "@/components/dashboard/PanelEditor";
import PanelFrame from "@/components/dashboard/PanelFrame";
import PanelView from "@/components/dashboard/PanelView";
import RowsDrawer, { type RowsRequest } from "@/components/dashboard/RowsDrawer";
import SelectionBar from "@/components/dashboard/SelectionBar";
import { Button, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorNote, Loading, Spinner } from "@/components/ui/Feedback";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { drillInto, isEmptySelection, pickedLabel, selectionFor, type DrillStep } from "@/lib/drill";
import { readError } from "@/lib/errors";
import type { Box } from "@/lib/grid";
import {
  DASHBOARDS_URL,
  DEFAULT_DASHBOARD_FILTERS,
  FIELDS_URL,
  categoryColorMap,
  QUERY_URL,
  settingsUrl,
  usedParameters,
  dashboardUrl,
  defaultConfig,
  drillDownUrl,
  effectiveFilters,
  isError,
  layoutUrl,
  panelUrl,
  panelsUrl,
} from "@/lib/insights";
import { recall, remember } from "@/lib/storage";
import { isText } from "@/lib/types";
import type {
  AnyPanelConfig,
  Catalogue,
  Category,
  DashboardDetail,
  DashboardParameters,
  DashboardSummary,
  Panel,
  PanelConfig,
  PanelFilters,
  Picked,
  QueryOutcome,
  Selection,
} from "@/lib/types";

const ACTIVE_KEY = "polycoin.dashboard.active";
const filtersKey = (id: string) => `polycoin.dashboard.filters.${id}`;
const LAYOUT_SAVE_DELAY_MS = 600;
const PARAMETER_SAVE_DELAY_MS = 600;
const MAX_DASHBOARDS = 20; // insights.models.MAX_DASHBOARDS_PER_USER
const MAX_PANELS = 30; // insights.models.MAX_PANELS_PER_DASHBOARD
const MAX_TITLE = 80;

// `seed` remounts the editor for a new panel opened with a different starting config.
type EditorState = { panel: Panel | null; title: string; showTitle: boolean; config: AnyPanelConfig; seed?: number };

// A click that is filtering the other panels. View state only: it is not saved.
type ActiveSelection = { source: string; mark: Selection; label: string; picked: Picked };
type RowsView = { title: string; request: RowsRequest };

// Each dashboard remembers its own filter bar in this browser.
function savedFilters(id: string): PanelFilters {
  const raw = recall(filtersKey(id));
  if (!raw) return DEFAULT_DASHBOARD_FILTERS;
  try {
    return { ...DEFAULT_DASHBOARD_FILTERS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_DASHBOARD_FILTERS;
  }
}

export default function DashboardPage() {
  const router = useRouter();
  const toast = useToast();
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [dashboards, setDashboards] = useState<DashboardSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DashboardDetail | null>(null);
  const [filters, setFilters] = useState<PanelFilters>(DEFAULT_DASHBOARD_FILTERS);
  const [results, setResults] = useState<Record<string, QueryOutcome>>({});
  // The exact config each result was computed for, so a panel whose config has just changed
  // (an edit, a drill-down) shows "Loading…" instead of the old answer drawn with the new config.
  const [answered, setAnswered] = useState<Record<string, string>>({});
  // Where each panel has been drilled to. View state: an edit or a tab change starts over.
  const [drills, setDrills] = useState<Record<string, DrillStep[]>>({});
  const [selection, setSelection] = useState<ActiveSelection | null>(null);
  const [rowsView, setRowsView] = useState<RowsView | null>(null);
  const [querying, setQuerying] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [editing, setEditing] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const editorSeed = useRef(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filtersRejected, setFiltersRejected] = useState(false);
  // The dashboard's parameter values; null until its detail has loaded. Saved to the server a
  // moment after the last change.
  const [parameters, setParameters] = useState<DashboardParameters | null>(null);
  const parametersFor = useRef<string | null>(null); // which dashboard `parameters` belongs to
  const parameterTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Layout changes waiting to be saved: panel id -> new box, for one dashboard.
  const pendingLayout = useRef<{ dashboardId: string; boxes: Map<string, Box> } | null>(null);
  const layoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- loading ----------------------------------------------------------------

  function selectDashboard(id: string | null) {
    flushLayout();
    setActiveId(id);
    setDetail(null);
    setParameters(null);
    parametersFor.current = null;
    setResults({});
    setAnswered({});
    setDrills({});
    setSelection(null);
    setRowsView(null);
    setFiltersRejected(false);
    if (id) {
      remember(ACTIVE_KEY, id);
      setFilters(savedFilters(id));
    }
  }

  useEffect(() => {
    async function loadSetup() {
      try {
        const [fieldsRes, categoriesRes, dashboardsRes] = await Promise.all([
          apiFetch(FIELDS_URL),
          apiFetch("/api/categories/"),
          apiFetch(DASHBOARDS_URL),
        ]);
        if (!fieldsRes.ok || !dashboardsRes.ok) {
          setError("Could not load your dashboards.");
          return;
        }
        setCatalogue(await fieldsRes.json());
        if (categoriesRes.ok) setCategories(await categoriesRes.json());
        const list: DashboardSummary[] = await dashboardsRes.json();
        setDashboards(list);
        const remembered = recall(ACTIVE_KEY);
        const first = list.find((d) => d.id === remembered) ?? list[0];
        if (first) {
          setActiveId(first.id);
          setFilters(savedFilters(first.id));
        }
      } catch {
        setError("Cannot reach the server.");
      } finally {
        setLoading(false);
      }
    }
    loadSetup();
  }, []);

  // The parameter values come from the server once per dashboard; after that this page owns them,
  // so reloading the panels (after an edit) can't undo a change still waiting to be saved.
  function acceptDetail(body: DashboardDetail) {
    setDetail(body);
    if (parametersFor.current !== body.id) {
      parametersFor.current = body.id;
      setParameters(body.settings.parameters);
    }
  }

  async function loadDetail(id: string) {
    const res = await apiFetch(dashboardUrl(id));
    if (res.ok) acceptDetail(await res.json());
    else setError(await readError(res, "Could not load this dashboard."));
  }

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false; // a slow response for a tab the user already left is ignored
    async function load(id: string) {
      const res = await apiFetch(dashboardUrl(id));
      if (cancelled) return;
      if (res.ok) acceptDetail(await res.json());
      else setError(await readError(res, "Could not load this dashboard."));
    }
    load(activeId);
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const used = useMemo(() => (detail ? usedParameters(detail.panels) : []), [detail]);

  // The config each panel is drawn with: as saved, or as drilled into.
  const configs = useMemo(
    () =>
      new Map(
        (detail?.panels ?? []).map((panel) => {
          const steps = drills[panel.id];
          return [panel.id, steps?.length ? steps[steps.length - 1].config : panel.config] as const;
        }),
      ),
    [detail, drills],
  );

  // What the batch query depends on, as a string: equal strings mean "nothing to re-run",
  // so moving or resizing panels (which changes `detail`) never costs a query.
  const queryBody = useMemo(() => {
    if (!detail) return null;
    const queries = detail.panels
      .map((panel) => ({ key: panel.id, spec: configs.get(panel.id) }))
      .filter(({ spec }) => spec && !isText(spec)); // a note has nothing to query
    // Parameters only matter when a panel follows one, so a dashboard that doesn't never re-runs
    // because of them.
    const sent = used.length && parameters ? { parameters } : {};
    // A pick filters every panel but the one it came from.
    const picked =
      selection && queries.some(({ key }) => key === selection.source)
        ? { selection: selection.mark, selection_source: selection.source }
        : {};
    return queries.length ? JSON.stringify({ filters, ...sent, ...picked, queries }) : null;
  }, [detail, configs, filters, parameters, used, selection]);

  useEffect(() => {
    if (!queryBody) return;
    let cancelled = false;
    async function run(body: string) {
      setQuerying(true);
      try {
        const res = await apiFetch(QUERY_URL, { method: "POST", body });
        if (cancelled) return;
        if (res.ok) {
          const sent: { key: string; spec: unknown }[] = JSON.parse(body).queries;
          setResults((await res.json()).results);
          setAnswered(Object.fromEntries(sent.map(({ key, spec }) => [key, JSON.stringify(spec)])));
          setFiltersRejected(false);
        } else {
          // A 400 here is the request as a whole: the filter bar, the parameters or a click filter.
          if (res.status === 400) setFiltersRejected(true);
          setError(await readError(res, "Could not load the charts."));
        }
      } catch {
        if (!cancelled) setError("Cannot reach the server.");
      } finally {
        if (!cancelled) setQuerying(false);
      }
    }
    run(queryBody);
    return () => {
      cancelled = true;
    };
  }, [queryBody, refreshTick]);

  // --- parameters -------------------------------------------------------------

  function changeParameters(next: DashboardParameters) {
    setParameters(next);
    if (!detail) return;
    const id = detail.id;
    if (parameterTimer.current) clearTimeout(parameterTimer.current);
    parameterTimer.current = setTimeout(async () => {
      const res = await apiFetch(settingsUrl(id), { method: "PUT", body: JSON.stringify({ parameters: next }) });
      if (!res.ok) toast.error(await readError(res, "Could not save the dashboard's parameters."));
    }, PARAMETER_SAVE_DELAY_MS);
  }

  // --- filters ----------------------------------------------------------------

  function changeFilters(next: PanelFilters) {
    setFilters(next);
    if (activeId) remember(filtersKey(activeId), JSON.stringify(next));
  }

  function resetFilters() {
    setError(null);
    setSelection(null);
    changeFilters(DEFAULT_DASHBOARD_FILTERS);
  }

  // --- layout -----------------------------------------------------------------

  async function saveLayout() {
    const pending = pendingLayout.current;
    pendingLayout.current = null;
    if (!pending || pending.boxes.size === 0) return;
    const items = [...pending.boxes.values()].map(({ id, x, y, w, h }) => ({ panel: id, x, y, w, h }));
    const res = await apiFetch(layoutUrl(pending.dashboardId), { method: "PUT", body: JSON.stringify(items) });
    if (!res.ok) {
      setError(await readError(res, "Could not save the layout."));
      await loadDetail(pending.dashboardId); // show what the server actually has
    }
  }

  // Save now instead of waiting for the timer (switching tabs, leaving the page).
  function flushLayout() {
    if (layoutTimer.current) clearTimeout(layoutTimer.current);
    layoutTimer.current = null;
    saveLayout();
  }

  useEffect(() => {
    return () => {
      if (layoutTimer.current) clearTimeout(layoutTimer.current);
      saveLayout(); // leaving the page: don't lose the last drag
    };
    // saveLayout only reads refs, so the first one is as good as any later one
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function commitLayout(next: Box[], changed: Box[]) {
    if (!detail) return;
    const byId = new Map(next.map((box) => [box.id, box]));
    setDetail({
      ...detail,
      panels: detail.panels.map((panel) => {
        const box = byId.get(panel.id);
        return box ? { ...panel, x: box.x, y: box.y, w: box.w, h: box.h } : panel;
      }),
    });
    // Several quick drags become one request: later moves of a panel replace earlier ones.
    if (pendingLayout.current?.dashboardId !== detail.id) {
      pendingLayout.current = { dashboardId: detail.id, boxes: new Map() };
    }
    for (const box of changed) pendingLayout.current.boxes.set(box.id, box);
    if (layoutTimer.current) clearTimeout(layoutTimer.current);
    layoutTimer.current = setTimeout(saveLayout, LAYOUT_SAVE_DELAY_MS);
  }

  // --- dashboards (tabs) --------------------------------------------------------

  async function createDashboard(name: string, template: "overview" | null) {
    const res = await apiFetch(DASHBOARDS_URL, {
      method: "POST",
      body: JSON.stringify(template ? { name, template } : { name }),
    });
    if (!res.ok) return setError(await readError(res, "Could not create the dashboard."));
    const created: DashboardSummary = await res.json();
    setDashboards((list) => [...list, created]);
    selectDashboard(created.id);
    setEditing(!template); // a blank dashboard opens ready for adding panels
  }

  async function renameDashboard(id: string, name: string) {
    const res = await apiFetch(dashboardUrl(id), { method: "PATCH", body: JSON.stringify({ name }) });
    if (!res.ok) return setError(await readError(res, "Could not rename the dashboard."));
    const renamed: DashboardSummary = await res.json();
    setDashboards((list) => list.map((d) => (d.id === id ? renamed : d)));
  }

  async function deleteDashboard(id: string) {
    const res = await apiFetch(dashboardUrl(id), { method: "DELETE" });
    if (!res.ok) return setError(await readError(res, "Could not delete the dashboard."));
    const rest = dashboards.filter((d) => d.id !== id);
    setDashboards(rest);
    setEditing(false);
    selectDashboard(rest[0]?.id ?? null);
  }

  // --- panels -----------------------------------------------------------------

  // A new panel at the bottom of the dashboard: from the editor, or straight from the AI builder.
  async function createPanel(title: string, showTitle: boolean, config: AnyPanelConfig): Promise<string | null> {
    if (!detail) return "The dashboard is still loading.";
    const res = await apiFetch(panelsUrl(detail.id), {
      method: "POST",
      body: JSON.stringify({ title, show_title: showTitle, config }),
    });
    if (!res.ok) return readError(res, "Could not save the panel.");
    await loadDetail(detail.id);
    toast.success("Panel added.");
    return null;
  }

  async function savePanel(title: string, showTitle: boolean, config: AnyPanelConfig): Promise<string | null> {
    if (!detail || !editor) return null;
    if (!editor.panel) {
      const problem = await createPanel(title, showTitle, config);
      if (!problem) setEditor(null);
      return problem;
    }
    const res = await apiFetch(panelUrl(detail.id, editor.panel.id), {
      method: "PATCH",
      body: JSON.stringify({ title, show_title: showTitle, config }),
    });
    if (!res.ok) return readError(res, "Could not save the panel.");
    setEditor(null);
    forget(editor.panel.id); // the saved config replaces whatever was drilled into
    await loadDetail(detail.id);
    toast.success("Panel saved.");
    return null;
  }

  // "Edit before adding" from the AI builder: the normal editor, filled in with its panel.
  function editAgentPanel(title: string, config: PanelConfig) {
    setAgentOpen(false);
    editorSeed.current += 1;
    setEditor({ panel: null, title, showTitle: true, config, seed: editorSeed.current });
  }

  async function duplicatePanel(panel: Panel) {
    if (!detail || !panel.config) return;
    const title = `${panel.title} (copy)`.slice(0, MAX_TITLE);
    const res = await apiFetch(panelsUrl(detail.id), {
      method: "POST",
      body: JSON.stringify({ title, show_title: panel.show_title, config: panel.config }), // no position: it goes at the bottom
    });
    if (!res.ok) return toast.error(await readError(res, "Could not duplicate the panel."));
    await loadDetail(detail.id);
    toast.success("Panel duplicated.");
  }

  async function deletePanel(panel: Panel) {
    if (!detail) return;
    const res = await apiFetch(panelUrl(detail.id, panel.id), { method: "DELETE" });
    if (!res.ok) return toast.error(await readError(res, "Could not delete the panel."));
    forget(panel.id);
    setDetail({ ...detail, panels: detail.panels.filter((p) => p.id !== panel.id) });
    toast.success("Panel deleted.");
  }

  // --- clicks on a chart --------------------------------------------------------

  // A panel's answer, only if it was computed for the config the panel has now.
  function outcomeFor(panel: Panel): QueryOutcome | undefined {
    const config = configs.get(panel.id);
    return config && answered[panel.id] === JSON.stringify(config) ? results[panel.id] : undefined;
  }

  // Forget a panel's drill-down and any filter it was making.
  function forget(panelId: string) {
    setDrills((all) => {
      const rest = { ...all };
      delete rest[panelId];
      return rest;
    });
    setSelection((current) => (current?.source === panelId ? null : current));
  }

  function trimDrill(panelId: string, depth: number) {
    setDrills((all) => ({ ...all, [panelId]: (all[panelId] ?? []).slice(0, depth) }));
    setSelection((current) => (current?.source === panelId ? null : current));
  }

  // The list behind a mark uses the same inputs as the chart it came from, including a click on
  // another panel that is filtering this one, so its total agrees with the bar.
  function openRows(panelId: string, title: string, config: PanelConfig, mark: Selection) {
    setRowsView({
      title,
      request: {
        filters,
        parameters: used.length && parameters ? parameters : undefined,
        config,
        mark,
        selection: selection && selection.source !== panelId ? selection.mark : undefined,
      },
    });
  }

  // What a click on a mark can do. Only what makes sense for that mark is offered.
  function actionsFor(panel: Panel, picked: Picked): MarkAction[] {
    const config = configs.get(panel.id);
    const outcome = outcomeFor(panel);
    if (!catalogue || !config || isText(config) || !outcome || isError(outcome)) return [];
    const label = pickedLabel(config, picked);
    const mark = selectionFor(config, picked);
    const actions: MarkAction[] = [];

    const step = drillInto(config, outcome, picked, categories, catalogue);
    if (step) {
      actions.push({
        id: "drill",
        label: `Drill into ${step.label}`,
        icon: <ArrowDownToLine size={15} />,
        run: () => {
          setDrills((all) => ({ ...all, [panel.id]: [...(all[panel.id] ?? []), step] }));
          setSelection((current) => (current?.source === panel.id ? null : current));
        },
      });
    }
    if (!isEmptySelection(mark)) {
      const active = selection?.source === panel.id && JSON.stringify(selection.mark) === JSON.stringify(mark);
      actions.push(
        active
          ? { id: "unfilter", label: "Clear the filter", icon: <FilterX size={15} />, run: () => setSelection(null) }
          : {
              id: "filter",
              label: "Filter other panels",
              icon: <Filter size={15} />,
              run: () => setSelection({ source: panel.id, mark, label, picked }),
            },
      );
      actions.push({
        id: "rows",
        label: "View transactions",
        icon: <List size={15} />,
        run: () => openRows(panel.id, `${panel.title}: ${label}`, config, mark),
      });
    }
    const url = drillDownUrl(config, outcome, effectiveFilters(config.filters, filters), picked, categories);
    if (url) {
      actions.push({ id: "open", label: "Open in Transactions", icon: <ExternalLink size={15} />, run: () => router.push(url) });
    }
    return actions;
  }

  // --- render -----------------------------------------------------------------

  const categoryColors = useMemo(() => categoryColorMap(categories), [categories]);
  const panelsById = useMemo(() => new Map((detail?.panels ?? []).map((p) => [p.id, p])), [detail]);
  const boxes = useMemo<Box[]>(
    () => (detail?.panels ?? []).map(({ id, x, y, w, h }) => ({ id, x, y, w, h })),
    [detail],
  );

  if (loading) return <Loading />;

  if (!catalogue) {
    return <ErrorNote>{error ?? "Could not load your dashboards."}</ErrorNote>;
  }

  const activeName = dashboards.find((d) => d.id === activeId)?.name;

  return (
    <>
      {dashboards.length === 0 ? (
        <Welcome onCreate={createDashboard} />
      ) : (
        <>
          <PageHeader
            title={activeName ?? "Dashboard"}
            subtitle={editing ? "Editing: drag, resize and recolour panels. Changes save automatically." : undefined}
            actions={
              <>
                {querying && (
                  <span className="flex items-center gap-1.5 text-sm text-ink-2">
                    <Spinner size={15} /> Updating…
                  </span>
                )}
                <IconButton
                  label="Refresh every panel"
                  variant="secondary"
                  icon={<RefreshCw size={16} />}
                  onClick={() => setRefreshTick((tick) => tick + 1)}
                />
                {editing && (
                  <Button
                    icon={<Sparkles size={16} />}
                    onClick={() => setAgentOpen(true)}
                    disabled={!detail || detail.panels.length >= MAX_PANELS}
                    title="Describe a panel and let your own AI build it"
                  >
                    AI
                  </Button>
                )}
                {editing && (
                  <Button
                    icon={<Plus size={16} />}
                    onClick={() => setEditor({ panel: null, title: "", showTitle: true, config: defaultConfig("bar") })}
                    disabled={(detail?.panels.length ?? 0) >= MAX_PANELS}
                    title={`Up to ${MAX_PANELS} panels per dashboard`}
                  >
                    Panel
                  </Button>
                )}
                <Button
                  variant={editing ? "primary" : "secondary"}
                  icon={editing ? <Check size={16} /> : <Pencil size={16} />}
                  aria-pressed={editing}
                  onClick={() => {
                    if (editing) flushLayout();
                    setEditing((on) => !on);
                  }}
                >
                  {editing ? "Done" : "Edit"}
                </Button>
              </>
            }
          />

          <DashboardTabs
            dashboards={dashboards}
            activeId={activeId}
            editing={editing}
            canCreate={dashboards.length < MAX_DASHBOARDS}
            onSelect={(id) => id !== activeId && selectDashboard(id)}
            onCreate={createDashboard}
            onRename={renameDashboard}
            onDelete={deleteDashboard}
          />

          <div className="my-4 space-y-3">
            <FilterBar filters={filters} categories={categories} onChange={changeFilters} />
            {parameters && (
              <ParameterBar catalogue={catalogue} parameters={parameters} used={used} onChange={changeParameters} />
            )}
            {selection && (
              <SelectionBar
                label={selection.label}
                panelTitle={panelsById.get(selection.source)?.title ?? ""}
                onClear={() => setSelection(null)}
              />
            )}
          </div>

          {error && (
            <ErrorNote className="mb-4 flex flex-wrap items-center gap-3">
              <span>{error}</span>
              {filtersRejected && (
                <button className="underline" onClick={resetFilters}>
                  Reset filters
                </button>
              )}
              <button className="ml-auto underline" onClick={() => setError(null)}>
                Dismiss
              </button>
            </ErrorNote>
          )}

          {!detail ? (
            <Loading />
          ) : detail.panels.length === 0 ? (
            <EmptyState
              icon={<LayoutDashboard size={22} aria-hidden />}
              title="This dashboard has no panels yet"
              action={
                <div className="flex flex-wrap justify-center gap-3">
                  <Button
                    variant="primary"
                    icon={<Plus size={16} />}
                    onClick={() => {
                      setEditing(true);
                      setEditor({ panel: null, title: "", showTitle: true, config: defaultConfig("bar") });
                    }}
                  >
                    Add your first panel
                  </Button>
                  <Button
                    icon={<Sparkles size={16} />}
                    onClick={() => {
                      setEditing(true);
                      setAgentOpen(true);
                    }}
                  >
                    Build one with AI
                  </Button>
                </div>
              }
            >
              A panel is one chart or number. Pick what goes on each axis, then drag and resize it.
            </EmptyState>
          ) : (
            <DashboardGrid
              boxes={boxes}
              editing={editing}
              onCommit={commitLayout}
              renderPanel={(id, editable) => {
                const panel = panelsById.get(id);
                if (!panel) return null;
                return (
                  <PanelFrame
                    title={panel.title}
                    showTitle={panel.show_title}
                    editing={editable}
                    onEdit={() =>
                      setEditor({
                        panel,
                        title: panel.title,
                        showTitle: panel.show_title,
                        config: panel.config ?? defaultConfig("bar"),
                      })
                    }
                    onDuplicate={() => duplicatePanel(panel)}
                    onDelete={() => deletePanel(panel)}
                  >
                    <PanelView
                      config={configs.get(panel.id) ?? null}
                      outcome={outcomeFor(panel)}
                      loading={querying}
                      categoryColors={categoryColors}
                      highlight={selection?.source === panel.id ? selection.picked.x : undefined}
                      title={panel.title}
                      trail={(drills[panel.id] ?? []).map((step) => step.label)}
                      onTrail={(depth) => trimDrill(panel.id, depth)}
                      interactive={!editing}
                      actionsFor={(picked) => actionsFor(panel, picked)}
                      labelFor={(picked) => {
                        const config = configs.get(panel.id);
                        return config && !isText(config) ? pickedLabel(config, picked) : "";
                      }}
                      onOpen={() => {
                        const config = configs.get(panel.id);
                        if (config && !isText(config)) openRows(panel.id, panel.title, config, {});
                      }}
                    />
                  </PanelFrame>
                );
              }}
            />
          )}
        </>
      )}

      {rowsView && <RowsDrawer title={rowsView.title} request={rowsView.request} onClose={() => setRowsView(null)} />}

      {agentOpen && detail && (
        <AgentDialog
          dashboard={{ filters, parameters }}
          categories={categories}
          canAdd={detail.panels.length < MAX_PANELS}
          onClose={() => setAgentOpen(false)}
          onAdd={(title, config) => createPanel(title, true, config)}
          onEditFirst={editAgentPanel}
        />
      )}

      {editor && detail && (
        <PanelEditor
          key={editor.panel?.id ?? `new-${editor.seed ?? 0}`}
          catalogue={catalogue}
          categories={categories}
          parameters={parameters ?? catalogue.parameters.defaults}
          initial={{ title: editor.title, showTitle: editor.showTitle, config: editor.config }}
          isNew={!editor.panel}
          dashboardFilters={filters}
          onCancel={() => setEditor(null)}
          onSave={savePanel}
        />
      )}
    </>
  );
}

// First visit: no dashboards yet. The template gives instant value; blank is for builders.
function Welcome({ onCreate }: { onCreate: (name: string, template: "overview" | null) => void }) {
  return (
    <section className="mx-auto mt-10 max-w-xl">
      <Card className="flex flex-col items-center gap-4 p-8! text-center">
        <span className="grid size-14 place-items-center rounded-full border-[1.5px] border-ink bg-canvas">
          <LayoutDashboard size={26} strokeWidth={1.75} aria-hidden />
        </span>
        <h1 className="text-[28px] font-semibold tracking-tight">Where did my money go?</h1>
        <p className="text-ink-2">
          Build dashboards of charts from your transactions, add panels, pick a chart and what goes
          on each axis, then drag and resize them. Start from a ready-made overview, or from an empty canvas.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button variant="primary" onClick={() => onCreate("Overview", "overview")}>
            Start with the Overview
          </Button>
          <Button onClick={() => onCreate("My dashboard", null)}>Blank dashboard</Button>
        </div>
      </Card>
    </section>
  );
}
