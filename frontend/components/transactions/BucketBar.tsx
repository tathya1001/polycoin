"use client";

// The category "buckets" above the transactions table. Each bucket is two things at once:
//   - a filter: click it and only that category's transactions are shown (click again: all)
//   - a drop target: drag one or many selected rows onto it and they move into that category
//
// It sticks to the top of the page while you scroll, so a bucket is always within reach of the
// row you are dragging.

import { useState, type DragEvent } from "react";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/cn";
import { readableOn } from "@/lib/colors";
import type { Category } from "@/lib/types";

// The drag payload's type: other drags (text, files, links) are ignored by the buckets.
export const TXN_DRAG_TYPE = "application/x-polycoin-transactions";

type Props = {
  categories: Category[];
  activeId: string; // the category being filtered on, or "" for all
  dragCount: number; // how many rows are being dragged right now (0: no drag)
  onFilter: (categoryId: string) => void;
  onDropInto: (categoryId: string, transactionIds: string[]) => void;
};

export function BucketBar({ categories, activeId, dragCount, onFilter, onDropInto }: Props) {
  const [over, setOver] = useState<string | null>(null);
  const dragging = dragCount > 0;

  function accepts(event: DragEvent) {
    return event.dataTransfer.types.includes(TXN_DRAG_TYPE);
  }

  function onDragOver(event: DragEvent, id: string) {
    if (!accepts(event)) return;
    event.preventDefault(); // this is what makes the element a valid drop target
    event.dataTransfer.dropEffect = "move";
    if (over !== id) setOver(id);
  }

  function onDrop(event: DragEvent, id: string) {
    if (!accepts(event)) return;
    event.preventDefault();
    setOver(null);
    try {
      const ids: unknown = JSON.parse(event.dataTransfer.getData(TXN_DRAG_TYPE));
      if (Array.isArray(ids) && ids.every((x) => typeof x === "string") && ids.length) {
        onDropInto(id, ids);
      }
    } catch {
      // not our payload: ignore
    }
  }

  return (
    <div className="sticky top-14 z-20 -mx-1 mb-4 bg-canvas/90 px-1 py-2 backdrop-blur md:top-0">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <p className="text-xs font-semibold tracking-wider text-ink-2 uppercase">Buckets</p>
        <p className="text-xs text-muted" aria-live="polite">
          {dragging
            ? `Drop ${dragCount === 1 ? "the transaction" : `${dragCount} transactions`} on a bucket`
            : "Click a bucket to filter. Drag rows onto one to categorise them."}
        </p>
      </div>
      <div role="toolbar" aria-label="Category buckets" className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onFilter("")}
          aria-pressed={activeId === ""}
          className={cn(
            "flex h-10 items-center gap-2 rounded-md border-[1.5px] border-ink px-3 text-sm font-medium transition-[transform,box-shadow,background-color] duration-150",
            activeId === "" ? "bg-ink text-white shadow-hard-sm" : "bg-surface hover:-translate-y-px hover:shadow-hard-sm",
            dragging && "opacity-40",
          )}
        >
          <Inbox size={15} aria-hidden />
          All
        </button>

        {categories.map((category) => {
          const active = activeId === category.id;
          const hot = dragging && over === category.id;
          return (
            <button
              key={category.id}
              type="button"
              onClick={() => onFilter(active ? "" : category.id)}
              aria-pressed={active}
              onDragOver={(e) => onDragOver(e, category.id)}
              onDragEnter={(e) => onDragOver(e, category.id)}
              onDragLeave={() => over === category.id && setOver(null)}
              onDrop={(e) => onDrop(e, category.id)}
              title={active ? `Showing ${category.name} only. Click to show all.` : `Show ${category.name} only`}
              style={hot ? { backgroundColor: category.color, color: readableOn(category.color) } : undefined}
              className={cn(
                "flex h-10 items-center gap-2 rounded-md border-[1.5px] px-3 text-sm font-medium transition-[transform,box-shadow,background-color] duration-150",
                active ? "border-ink bg-ink text-white shadow-hard-sm" : "border-ink bg-surface",
                !dragging && !active && "hover:-translate-y-px hover:shadow-hard-sm",
                // While dragging, every bucket shows it can take the rows; the one under the
                // pointer fills with its own colour and lifts.
                dragging && !hot && "border-dashed",
                hot && "-translate-y-0.5 scale-105 border-solid shadow-hard",
              )}
            >
              <span
                aria-hidden
                className="size-3 shrink-0 rounded-full border border-ink"
                style={{ backgroundColor: category.color }}
              />
              {category.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
