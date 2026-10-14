"use client";

// The Insights dashboard: tabs of user-built dashboards, each a grid of chart panels.
//
// Data flow (see dev-docs/phase-5-plan.md):
//   - GET  /api/dashboards/        the tabs
//   - GET  /api/dashboards/{id}/   the active tab's panels (decrypted titles and configs)
//   - POST /api/insights/query/    every panel's chart data in ONE request, so the server
//                                  decrypts the user's transactions once, not once per panel
//   - PUT  /api/dashboards/{id}/layout/   panel positions, saved after a drag or resize
//
// Every insights call shares a 600/hour budget, so queries only re-run when a panel's
// config or the filters really change (not when panels move), and layout saves are batched.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, LayoutDashboard, Pencil, Plus, RefreshCw } from "lucide-react";
import PanelBody from "@/components/charts/PanelBody";
import DashboardGrid from "@/components/dashboard/DashboardGrid";
import DashboardTabs from "@/components/dashboard/DashboardTabs";
import FilterBar from "@/components/dashboard/FilterBar";
import PanelEditor from "@/components/dashboard/PanelEditor";
import PanelFrame from "@/components/dashboard/PanelFrame";
import { Button, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorNote, Loading, Spinner } from "@/components/ui/Feedback";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import type { Box } from "@/lib/grid";
import {
  DASHBOARDS_URL,
  DEFAULT_DASHBOARD_FILTERS,
  FIELDS_URL,
  categoryColorMap,
  QUERY_URL,
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
import type {
  Catalogue,
  Category,
  DashboardDetail,
  DashboardSummary,
  Panel,
  PanelConfig,
  PanelFilters,
  QueryOutcome,
} from "@/lib/types";

const ACTIVE_KEY = "polycoin.dashboard.active";
const filtersKey = (id: string) => `polycoin.dashboard.filters.${id}`;
const LAYOUT_SAVE_DELAY_MS = 600;
const MAX_DASHBOARDS = 20; // insights.models.MAX_DASHBOARDS_PER_USER
const MAX_PANELS = 30; // insights.models.MAX_PANELS_PER_DASHBOARD
const MAX_TITLE = 80;

type EditorState = { panel: Panel | null; title: string; config: PanelConfig };

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
  const [querying, setQuerying] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [editing, setEditing] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filtersRejected, setFiltersRejected] = useState(false);

  // Layout changes waiting to be saved: panel id -> new box, for one dashboard.
  const pendingLayout = useRef<{ dashboardId: string; boxes: Map<string, Box> } | null>(null);
  const layoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- loading ----------------------------------------------------------------

  function selectDashboard(id: string | null) {
    flushLayout();
    setActiveId(id);
    setDetail(null);
    setResults({});
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

  async function loadDetail(id: string) {
    const res = await apiFetch(dashboardUrl(id));
    if (res.ok) setDetail(await res.json());
    else setError(await readError(res, "Could not load this dashboard."));
  }

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false; // a slow response for a tab the user already left is ignored
    async function load(id: string) {
      const res = await apiFetch(dashboardUrl(id));
      if (cancelled) return;
      if (res.ok) setDetail(await res.json());
      else setError(await readError(res, "Could not load this dashboard."));
    }
    load(activeId);
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // What the batch query depends on, as a string: equal strings mean "nothing to re-run",
  // so moving or resizing panels (which changes `detail`) never costs a query.
  const queryBody = useMemo(() => {
    if (!detail) return null;
    const queries = detail.panels
      .filter((panel) => panel.config)
      .map((panel) => ({ key: panel.id, spec: panel.config }));
    return queries.length ? JSON.stringify({ filters, queries }) : null;
  }, [detail, filters]);

  useEffect(() => {
    if (!queryBody) return;
    let cancelled = false;
    async function run(body: string) {
      setQuerying(true);
      try {
        const res = await apiFetch(QUERY_URL, { method: "POST", body });
        if (cancelled) return;
        if (res.ok) {
          setResults((await res.json()).results);
          setFiltersRejected(false);
        } else {
          if (res.status === 400) setFiltersRejected(true); // only the filter bar can 400 here
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

  // --- filters ----------------------------------------------------------------

  function changeFilters(next: PanelFilters) {
    setFilters(next);
    if (activeId) remember(filtersKey(activeId), JSON.stringify(next));
  }

  function resetFilters() {
    setError(null);
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

  async function savePanel(title: string, config: PanelConfig): Promise<string | null> {
    if (!detail || !editor) return null;
    const res = editor.panel
      ? await apiFetch(panelUrl(detail.id, editor.panel.id), {
          method: "PATCH",
          body: JSON.stringify({ title, config }),
        })
      : await apiFetch(panelsUrl(detail.id), { method: "POST", body: JSON.stringify({ title, config }) });
    if (!res.ok) return readError(res, "Could not save the panel.");
    setEditor(null);
    await loadDetail(detail.id);
    toast.success(editor.panel ? "Panel saved." : "Panel added.");
    return null;
  }

  async function duplicatePanel(panel: Panel) {
    if (!detail || !panel.config) return;
    const title = `${panel.title} (copy)`.slice(0, MAX_TITLE);
    const res = await apiFetch(panelsUrl(detail.id), {
      method: "POST",
      body: JSON.stringify({ title, config: panel.config }), // no position: it goes at the bottom
    });
    if (!res.ok) return toast.error(await readError(res, "Could not duplicate the panel."));
    await loadDetail(detail.id);
    toast.success("Panel duplicated.");
  }

  async function deletePanel(panel: Panel) {
    if (!detail) return;
    const res = await apiFetch(panelUrl(detail.id, panel.id), { method: "DELETE" });
    if (!res.ok) return toast.error(await readError(res, "Could not delete the panel."));
    setDetail({ ...detail, panels: detail.panels.filter((p) => p.id !== panel.id) });
    toast.success("Panel deleted.");
  }

  // A click on a bar or slice opens the transactions behind it.
  function drillDown(panel: Panel, picked: Parameters<typeof drillDownUrl>[3]) {
    const outcome = results[panel.id];
    if (!panel.config || !outcome || isError(outcome)) return;
    const url = drillDownUrl(
      panel.config,
      outcome,
      effectiveFilters(panel.config.filters, filters),
      picked,
      categories,
    );
    if (url) router.push(url);
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
                    icon={<Plus size={16} />}
                    onClick={() => setEditor({ panel: null, title: "", config: defaultConfig("bar") })}
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

          <div className="my-4">
            <FilterBar filters={filters} categories={categories} onChange={changeFilters} />
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
                <Button
                  variant="primary"
                  icon={<Plus size={16} />}
                  onClick={() => {
                    setEditing(true);
                    setEditor({ panel: null, title: "", config: defaultConfig("bar") });
                  }}
                >
                  Add your first panel
                </Button>
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
                    editing={editable}
                    onEdit={() =>
                      setEditor({ panel, title: panel.title, config: panel.config ?? defaultConfig("bar") })
                    }
                    onDuplicate={() => duplicatePanel(panel)}
                    onDelete={() => deletePanel(panel)}
                  >
                    <PanelBody
                      config={panel.config}
                      outcome={results[panel.id]}
                      loading={querying}
                      categoryColors={categoryColors}
                      onPick={editing ? undefined : (picked) => drillDown(panel, picked)}
                    />
                  </PanelFrame>
                );
              }}
            />
          )}
        </>
      )}

      {editor && detail && (
        <PanelEditor
          key={editor.panel?.id ?? "new"}
          catalogue={catalogue}
          categories={categories}
          initial={{ title: editor.title, config: editor.config }}
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
