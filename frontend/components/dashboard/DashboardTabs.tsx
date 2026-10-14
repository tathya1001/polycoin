"use client";

import { useState, type FormEvent } from "react";
import { LayoutTemplate, Plus, X } from "lucide-react";
import { cn } from "@/lib/cn";
import type { DashboardSummary } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/Confirm";
import { Input } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";

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

// One tab per dashboard, like the sheet tabs of a spreadsheet. Double-click a tab to rename it.
export default function DashboardTabs(props: Props) {
  const { dashboards, activeId, editing, canCreate, onSelect, onCreate, onRename, onDelete } = props;
  const confirm = useConfirm();
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [newName, setNewName] = useState("");

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

  function create(event: FormEvent | null, template: "overview" | null, close: () => void) {
    event?.preventDefault();
    onCreate(newName.trim() || (template ? "Overview" : "New dashboard"), template);
    close();
    setNewName("");
  }

  async function askDelete(dashboard: DashboardSummary) {
    const ok = await confirm({
      title: `Delete "${dashboard.name}"?`,
      message: "The dashboard and all its panels are deleted. This can't be undone.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (ok) onDelete(dashboard.id);
  }

  return (
    <div role="tablist" aria-label="Dashboards" className="flex flex-wrap items-end gap-1.5 border-b-[1.5px] border-ink">
      {dashboards.map((dashboard) => {
        const active = dashboard.id === activeId;
        return (
          <div
            key={dashboard.id}
            className={cn(
              "mb-[-1.5px] flex h-10 items-center gap-1.5 rounded-t-md border-[1.5px] px-4 text-sm transition-colors duration-150",
              active
                ? "border-ink border-b-surface bg-surface font-semibold"
                : "border-transparent text-ink-2 hover:bg-wash hover:text-ink",
            )}
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
                className="w-40 border-b-[1.5px] border-ink bg-transparent outline-none"
                aria-label="Dashboard name"
              />
            ) : (
              <button
                role="tab"
                aria-selected={active}
                onClick={() => onSelect(dashboard.id)}
                onDoubleClick={() => startRename(dashboard)}
                title="Double-click to rename"
                className="h-full"
              >
                {dashboard.name}
              </button>
            )}
            {active && editing && renaming !== dashboard.id && (
              <button
                onClick={() => askDelete(dashboard)}
                className="grid size-5 place-items-center rounded-full text-muted hover:bg-[#fee2e2] hover:text-neg"
                aria-label={`Delete ${dashboard.name}`}
                title="Delete this dashboard"
              >
                <X size={13} aria-hidden />
              </button>
            )}
          </div>
        );
      })}

      <div className="mb-1 ml-1">
        <Popover
          trigger={(p) => (
            <Button
              size="sm"
              variant="ghost"
              icon={<Plus size={15} />}
              disabled={!canCreate}
              title={canCreate ? "New dashboard" : "You have the maximum number of dashboards"}
              onClick={p.onClick}
              aria-expanded={p["aria-expanded"]}
              aria-haspopup={p["aria-haspopup"]}
            >
              New
            </Button>
          )}
          className="w-72"
        >
          {(close) => (
            <form onSubmit={(e) => create(e, null, close)} className="space-y-3">
              <Input
                dense
                autoFocus
                value={newName}
                maxLength={MAX_NAME}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Dashboard name"
                aria-label="New dashboard name"
              />
              <div className="flex flex-col gap-2">
                <Button type="submit" size="sm">
                  Blank dashboard
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  icon={<LayoutTemplate size={15} />}
                  onClick={() => create(null, "overview", close)}
                >
                  From the Overview template
                </Button>
              </div>
            </form>
          )}
        </Popover>
      </div>
    </div>
  );
}
