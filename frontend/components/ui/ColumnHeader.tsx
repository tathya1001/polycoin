"use client";

// A table header cell with a spreadsheet-style filter and a drag handle for its width.

import { useCallback, useRef, useState, type ComponentProps, type PointerEvent, type ReactNode } from "react";
import { ListFilter } from "lucide-react";
import { arrowStep, clampWidth, defaultWidths, parseWidths, totalWidth, type ColumnSpec, type Widths } from "@/lib/columnWidths";
import { cn } from "@/lib/cn";
import { recall, remember } from "@/lib/storage";
import { Popover } from "@/components/ui/Popover";
import { Th } from "@/components/ui/Table";

// The widths of a table's columns, kept in this browser under `storageKey`.
export function useColumnWidths(storageKey: string, columns: ColumnSpec[]) {
  const [widths, setWidths] = useState<Widths>(() => parseWidths(recall(storageKey), columns));

  const resize = useCallback(
    (spec: ColumnSpec, width: number) => setWidths((current) => ({ ...current, [spec.key]: clampWidth(spec, width) })),
    [],
  );
  const save = useCallback(
    (spec: ColumnSpec, width: number) => {
      setWidths((current) => {
        const next = { ...current, [spec.key]: clampWidth(spec, width) };
        remember(storageKey, JSON.stringify(next));
        return next;
      });
    },
    [storageKey],
  );
  const reset = useCallback(() => {
    const next = defaultWidths(columns);
    setWidths(next);
    remember(storageKey, JSON.stringify(next));
  }, [storageKey, columns]);

  const changed = columns.some((column) => widths[column.key] !== column.width);
  return { widths, total: totalWidth(columns, widths), changed, resize, save, reset };
}

function ResizeHandle({
  spec,
  label,
  width,
  onResize,
  onSave,
}: {
  spec: ColumnSpec;
  label: string;
  width: number;
  onResize: (spec: ColumnSpec, width: number) => void;
  onSave: (spec: ColumnSpec, width: number) => void;
}) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  function start(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { startX: event.clientX, startWidth: width };
  }

  function move(event: PointerEvent<HTMLDivElement>) {
    if (drag.current) onResize(spec, drag.current.startWidth + event.clientX - drag.current.startX);
  }

  function end(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    onSave(spec, drag.current.startWidth + event.clientX - drag.current.startX);
    drag.current = null;
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label} column`}
      aria-valuenow={width}
      aria-valuemin={spec.min}
      tabIndex={0}
      title="Drag to resize. Double-click to reset."
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={() => onSave(spec, spec.width)}
      onKeyDown={(event) => {
        const step = arrowStep(event.key);
        if (!step) return;
        event.preventDefault();
        onSave(spec, width + step);
      }}
      className="group/handle absolute inset-y-0 -right-1 z-10 flex w-2 cursor-col-resize touch-none justify-center outline-none select-none"
    >
      <span
        aria-hidden
        className="w-0.5 bg-transparent transition-colors duration-150 group-hover/handle:bg-edge group-focus-visible/handle:bg-ink"
      />
    </div>
  );
}

export function ColumnHeader({
  spec,
  label,
  width,
  onResize,
  onSave,
  filtered = false,
  filter,
  align = "left",
  className,
  ...rest
}: {
  spec: ColumnSpec;
  label: string;
  width: number;
  onResize: (spec: ColumnSpec, width: number) => void;
  onSave: (spec: ColumnSpec, width: number) => void;
  filtered?: boolean; // this column has a filter on: the icon stays solid, with or without hover
  filter?: ReactNode;
  align?: "left" | "right";
} & Omit<ComponentProps<"th">, "align">) {
  return (
    <Th align={align} className={cn("group/header relative", className)} {...rest}>
      <span className={cn("flex min-w-0 items-center gap-1", align === "right" && "justify-end")}>
        <span className="truncate">{label}</span>
        {filter && (
          <Popover
            floating
            className="w-64"
            trigger={(p) => (
              <button
                type="button"
                aria-label={filtered ? `Filter ${label}: on` : `Filter ${label}`}
                onClick={p.onClick}
                aria-expanded={p["aria-expanded"]}
                aria-haspopup={p["aria-haspopup"]}
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-sm transition-[opacity,background-color] duration-150 focus-visible:opacity-100",
                  // Always in sight, quietly: a filter nobody can find isn't a filter.
                  filtered
                    ? "bg-fill text-on-fill"
                    : "text-ink-2 opacity-60 group-hover/header:opacity-100 hover:bg-canvas aria-expanded:opacity-100",
                )}
              >
                <ListFilter size={14} aria-hidden />
              </button>
            )}
          >
            {filter}
          </Popover>
        )}
      </span>
      {spec.min !== undefined && (
        <ResizeHandle spec={spec} label={label} width={width} onResize={onResize} onSave={onSave} />
      )}
    </Th>
  );
}
