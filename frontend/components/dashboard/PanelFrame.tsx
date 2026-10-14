"use client";

import type { ReactNode } from "react";
import { Copy, GripVertical, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { IconButton } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/Confirm";
import { Popover } from "@/components/ui/Popover";

type Props = {
  title: string;
  editing: boolean; // Edit mode: show the grip and the menu
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  children: ReactNode;
};

// The card around one chart: a header and, in Edit mode, a menu. The grid lays an
// invisible move handle over the header, so dragging the title moves the panel.
export default function PanelFrame({ title, editing, onEdit, onDuplicate, onDelete, children }: Props) {
  const confirm = useConfirm();

  async function askDelete() {
    const ok = await confirm({
      title: `Delete "${title || "this panel"}"?`,
      message: "The chart is removed from this dashboard.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (ok) onDelete();
  }

  return (
    <section
      className={cn(
        "flex h-full flex-col overflow-hidden rounded-md border-[1.5px] bg-surface transition-shadow duration-150",
        editing ? "border-dashed border-ink" : "border-ink shadow-hard-sm",
      )}
    >
      <header className="flex items-center gap-2 border-b border-hairline px-3 py-2">
        {editing && <GripVertical size={16} className="shrink-0 text-muted" aria-hidden />}
        <h2 className={cn("min-w-0 flex-1 truncate text-sm font-semibold", editing && "select-none")} title={title}>
          {title || <span className="text-muted">Untitled</span>}
        </h2>
        {editing && (
          <Popover
            align="right"
            className="w-44 p-1.5!"
            trigger={(p) => (
              <IconButton
                label="Panel menu"
                size="sm"
                icon={<MoreHorizontal size={16} />}
                onClick={p.onClick}
                aria-expanded={p["aria-expanded"]}
                aria-haspopup={p["aria-haspopup"]}
              />
            )}
          >
            {(close) => (
              <div className="flex flex-col text-sm">
                <MenuItem icon={<Pencil size={15} />} onClick={() => { close(); onEdit(); }}>
                  Edit…
                </MenuItem>
                <MenuItem icon={<Copy size={15} />} onClick={() => { close(); onDuplicate(); }}>
                  Duplicate
                </MenuItem>
                <MenuItem icon={<Trash2 size={15} />} danger onClick={() => { close(); askDelete(); }}>
                  Delete…
                </MenuItem>
              </div>
            )}
          </Popover>
        )}
      </header>
      <div className="min-h-0 flex-1 p-2">{children}</div>
    </section>
  );
}

function MenuItem({
  children,
  icon,
  onClick,
  danger,
}: {
  children: ReactNode;
  icon: ReactNode;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-sm px-2.5 py-1.5 text-left hover:bg-wash",
        danger && "text-neg hover:bg-[#fee2e2]",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
