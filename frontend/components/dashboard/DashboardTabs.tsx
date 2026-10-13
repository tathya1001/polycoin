"use client";

import { useState, type FormEvent } from "react";
import type { DashboardSummary } from "@/lib/types";

const MAX_NAME = 60; // DashboardSerializer.name max_length

type Props = {
  dashboards: DashboardSummary[];
  activeId: string | null;
  editing: boolean;
  canCreate: boolean; // false once the user has the maximum number of dashboards
  onSelect: (id: string) => void;
  onCreate: (name: string, template: "overview" | null) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
};

// One tab per dashboard, like Tableau's sheet tabs. Double-click a tab to rename it.
export default function DashboardTabs(props: Props) {
  const { dashboards, activeId, editing, canCreate, onSelect, onCreate, onRename, onDelete } = props;
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  function startRename(dashboard: DashboardSummary) {
    setRenaming(dashboard.id);
    setDraftName(dashboard.name);
  }

  function finishRename() {
    const name = draftName.trim();
    const current = dashboards.find((d) => d.id === renaming);
    if (renaming && name && current && name !== current.name) onRename(renaming, name);
    setRenaming(null);
  }

  function create(event: FormEvent, template: "overview" | null) {
    event.preventDefault();
    onCreate(newName.trim() || (template ? "Overview" : "New dashboard"), template);
    setCreating(false);
    setNewName("");
  }

  const doomed = dashboards.find((d) => d.id === confirmDelete);

  return (
    <div className="flex flex-col gap-2">
      <div role="tablist" className="flex flex-wrap items-end gap-1 border-b border-gray-200 dark:border-gray-800">
        {dashboards.map((dashboard) => {
          const active = dashboard.id === activeId;
          return (
            <div
              key={dashboard.id}
              className={`-mb-px flex items-center gap-1 rounded-t-md border px-3 py-1.5 text-sm ${
                active
                  ? "border-gray-200 border-b-background bg-background font-medium dark:border-gray-800"
                  : "border-transparent text-gray-500 hover:text-current"
              }`}
            >
              {renaming === dashboard.id ? (
                <input
                  autoFocus
                  value={draftName}
                  maxLength={MAX_NAME}
                  onChange={(e) => setDraftName(e.target.value)}
                  onBlur={finishRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") finishRename();
                    if (e.key === "Escape") setRenaming(null);
                  }}
                  className="w-40 border-b border-gray-400 bg-transparent outline-none"
                  aria-label="Dashboard name"
                />
              ) : (
                <button
                  role="tab"
                  aria-selected={active}
                  onClick={() => onSelect(dashboard.id)}
                  onDoubleClick={() => startRename(dashboard)}
                  title="Double-click to rename"
                >
                  {dashboard.name}
                </button>
              )}
              {active && editing && renaming !== dashboard.id && (
                <button
                  onClick={() => setConfirmDelete(dashboard.id)}
                  className="ml-1 text-gray-400 hover:text-red-600"
                  aria-label={`Delete ${dashboard.name}`}
                  title="Delete this dashboard"
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
        <button
          onClick={() => setCreating((open) => !open)}
          disabled={!canCreate}
          className="mb-1 ml-1 rounded px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 hover:text-current disabled:opacity-40 dark:hover:bg-gray-900"
          title={canCreate ? "New dashboard" : "You have the maximum number of dashboards"}
        >
          + New
        </button>
      </div>

      {creating && (
        <form
          onSubmit={(e) => create(e, null)}
          className="flex flex-wrap items-center gap-2 rounded-md border border-gray-200 p-2 text-sm dark:border-gray-800"
        >
          <input
            autoFocus
            value={newName}
            maxLength={MAX_NAME}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Dashboard name"
            className="border p-1"
          />
          <button type="submit" className="border px-3 py-1">Blank</button>
          <button type="button" onClick={(e) => create(e, "overview")} className="bg-black px-3 py-1 text-white dark:bg-white dark:text-black">
            From the Overview template
          </button>
          <button type="button" onClick={() => setCreating(false)} className="underline">Cancel</button>
        </form>
      )}

      {doomed && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm dark:border-red-900 dark:bg-red-950">
          <span>Delete “{doomed.name}” and all its panels? This can&apos;t be undone.</span>
          <button className="text-red-600 underline" onClick={() => { setConfirmDelete(null); onDelete(doomed.id); }}>
            Delete
          </button>
          <button className="underline" onClick={() => setConfirmDelete(null)}>Cancel</button>
        </div>
      )}
    </div>
  );
}
