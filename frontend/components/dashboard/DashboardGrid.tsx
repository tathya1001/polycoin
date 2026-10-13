"use client";

// The Tableau-style canvas: panels on a 12-column grid that you drag by their header and
// resize from the bottom-right corner (Edit mode only). The layout rules live in lib/grid.ts;
// this component only turns pointer movement into grid moves and draws the result.
//
// While a drag is in progress the grid shows a live preview (other panels slide out of the
// way). Nothing is saved until the pointer is released, and then only if something changed.

import { useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import {
  byPosition,
  changedBoxes,
  gridHeight,
  moveBox,
  resizeBox,
  toGridDelta,
  toPixels,
  type Box,
} from "@/lib/grid";

const NARROW = 768; // below this width panels stack in one read-only column

type HandleProps = {
  // Which panel and which gesture this handle starts. The pointer handlers below are the
  // same functions for every handle and read these, so render never builds closures over refs.
  "data-panel": string;
  "data-gesture": Gesture["mode"];
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLElement>) => void;
  onPointerCancel: (event: PointerEvent<HTMLElement>) => void;
  style: CSSProperties;
};

type Gesture = {
  id: string;
  mode: "move" | "resize";
  startX: number;
  startY: number;
  box: Box; // the panel as it was when the gesture began
  base: Box[]; // the whole layout as it was when the gesture began
};

type Props = {
  boxes: Box[];
  editing: boolean;
  onCommit: (next: Box[], changed: Box[]) => void;
  // Draws one panel. `editable` is true when it can be moved, resized and changed. The grid
  // draws the move and resize handles itself, on top of whatever this returns.
  renderPanel: (id: string, editable: boolean) => ReactNode;
};

export default function DashboardGrid({ boxes, editing, onCommit, renderPanel }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  // The layout mid-gesture, and which panel is being moved or resized.
  const [preview, setPreview] = useState<{ boxes: Box[]; id: string } | null>(null);
  const gesture = useRef<Gesture | null>(null);
  const latest = useRef<Box[] | null>(null);

  // Track the container's width: column widths, and the narrow layout, depend on it.
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const narrow = width > 0 && width < NARROW;
  const canEdit = editing && !narrow;
  const shown = preview?.boxes ?? boxes;

  function onPointerDown(event: PointerEvent<HTMLElement>) {
    if (event.button !== 0) return;
    const id = event.currentTarget.dataset.panel;
    const mode = event.currentTarget.dataset.gesture as Gesture["mode"];
    const box = boxes.find((b) => b.id === id);
    if (!id || !box) return;
    event.preventDefault();
    // Capture: keep receiving moves even when the pointer leaves the handle.
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { id, mode, startX: event.clientX, startY: event.clientY, box, base: boxes };
    latest.current = boxes;
    setPreview({ boxes, id });
  }

  function onPointerMove(event: PointerEvent<HTMLElement>) {
    const g = gesture.current;
    if (!g) return;
    const { cols, rows } = toGridDelta(event.clientX - g.startX, event.clientY - g.startY, width);
    const next =
      g.mode === "move"
        ? moveBox(g.base, g.id, g.box.x + cols, g.box.y + rows)
        : resizeBox(g.base, g.id, g.box.w + cols, g.box.h + rows);
    latest.current = next;
    setPreview({ boxes: next, id: g.id });
  }

  function onPointerUp() {
    const g = gesture.current;
    const next = latest.current;
    gesture.current = null;
    latest.current = null;
    setPreview(null);
    if (!g || !next) return;
    const changed = changedBoxes(g.base, next);
    if (changed.length) onCommit(next, changed);
  }

  function onPointerCancel() {
    gesture.current = null; // e.g. the browser took over for scrolling: drop the gesture
    latest.current = null;
    setPreview(null);
  }

  function handle(id: string, mode: Gesture["mode"]): HandleProps {
    return {
      "data-panel": id,
      "data-gesture": mode,
      style: { touchAction: "none", cursor: mode === "move" ? "grab" : "nwse-resize" },
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel,
    };
  }

  if (narrow) {
    return (
      <div ref={container} className="flex flex-col gap-3">
        {[...boxes].sort(byPosition).map((box) => (
          <div key={box.id} style={{ height: toPixels(box, NARROW).height }}>
            {renderPanel(box.id, false)}
          </div>
        ))}
      </div>
    );
  }

  const active = preview?.id;
  return (
    <div
      ref={container}
      className={`relative ${canEdit ? "rounded-lg outline-1 outline-offset-4 outline-gray-300 outline-dashed dark:outline-gray-700" : ""}`}
      style={{ height: Math.max(gridHeight(shown), canEdit ? 200 : 0) }}
    >
      {width > 0 &&
        shown.map((box) => {
          const { left, top, width: w, height: h } = toPixels(box, width);
          const moving = box.id === active;
          return (
            <div
              key={box.id}
              className={`absolute ${moving ? "z-20 opacity-90 shadow-xl" : "z-10 transition-[left,top,width,height] duration-150"}`}
              style={{ left, top, width: w, height: h }}
            >
              {renderPanel(box.id, canEdit)}
              {canEdit && (
                // An invisible strip over the panel's header: grab it to move the panel. It stops
                // short of the right edge so the panel's ⋯ menu button stays clickable.
                <span
                  {...handle(box.id, "move")}
                  aria-label="Move panel"
                  title="Drag to move"
                  className="absolute left-0 right-10 top-0 h-8"
                />
              )}
              {canEdit && (
                <span
                  {...handle(box.id, "resize")}
                  aria-label="Resize panel"
                  title="Drag to resize"
                  className="absolute bottom-0.5 right-0.5 h-4 w-4 rounded-sm border-b-2 border-r-2 border-gray-400 hover:border-current"
                />
              )}
            </div>
          );
        })}
    </div>
  );
}
