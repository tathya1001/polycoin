"use client";

// The dashboard canvas: panels on a 12-column grid that you drag by their header and
// resize from the bottom-right corner (Edit mode only). The layout rules live in lib/grid.ts;
// this component only turns pointer movement into grid moves and draws the result.
//
// While a drag is in progress the grid shows a live preview (other panels slide out of the
// way). Nothing is saved until the pointer is released, and then only if something changed.
//
// Why dragging feels smooth:
//   - The dragged panel follows the pointer pixel by pixel. Its transform is written straight
//     to the DOM on every pointer event, so React does not re-render 100+ times a second.
//   - React only re-renders when the panel enters a different grid cell (the layout changed).
//   - Panels are positioned with `transform`, not left/top, so sliding them is a cheap
//     compositor move instead of a layout pass. The dragged panel's own landing in its cell
//     is animated the same way.
//   - In Edit mode every panel gets its own compositor layer (will-change), so sliding one
//     never repaints its chart.
//   - A dashed placeholder shows the cell the panel will land in.
//   - A panel's contents (its chart) are not re-rendered when only positions change: see
//     PanelSlot. While you drag, the page above does not re-render, so renderPanel is stable.

import { memo, useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
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
const LAND_MS = 170; // how long the dragged panel takes to settle into its cell
const LAND_EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";

type HandleProps = {
  // Which panel and which gesture this handle starts. The pointer handlers below are the
  // same functions for every handle and read these, so render never builds closures over refs.
  "data-panel": string;
  "data-gesture": Gesture["mode"];
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLElement>) => void;
  onPointerCancel: (event: PointerEvent<HTMLElement>) => void;
  onLostPointerCapture: (event: PointerEvent<HTMLElement>) => void;
  style: CSSProperties;
};

type Gesture = {
  id: string;
  mode: "move" | "resize";
  startX: number;
  startY: number;
  box: Box; // the panel as it was when the gesture began
  base: Box[]; // the whole layout as it was when the gesture began
  element: HTMLElement | null; // the panel's wrapper: moved directly, without React
  handle: HTMLElement;
  left: number; // the panel's pixel position when the gesture began
  top: number;
  cols: number; // the whole-cell offset last rendered: re-render only when it changes
  rows: number;
};

type Preview = {
  boxes: Box[];
  id: string;
  mode: Gesture["mode"];
  // Where the dragged panel started, in pixels. Constant for the whole gesture, so React
  // never rewrites the transform the pointer handler is animating by hand.
  origin: { left: number; top: number };
};

type Props = {
  boxes: Box[];
  editing: boolean;
  onCommit: (next: Box[], changed: Box[]) => void;
  // Draws one panel. `editable` is true when it can be moved, resized and changed. The grid
  // draws the move and resize handles itself, on top of whatever this returns.
  renderPanel: (id: string, editable: boolean) => ReactNode;
};

const translate = (left: number, top: number) => `translate3d(${left}px, ${top}px, 0)`;

// One panel's contents. memo skips the render (and so the chart) whenever its three props are
// unchanged, which is every layout change during a drag.
const PanelSlot = memo(function PanelSlot({
  id,
  editable,
  renderPanel,
}: {
  id: string;
  editable: boolean;
  renderPanel: Props["renderPanel"];
}) {
  return <>{renderPanel(id, editable)}</>;
});

export default function DashboardGrid({ boxes, editing, onCommit, renderPanel }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  // The layout mid-gesture, and which panel is being moved or resized.
  const [preview, setPreview] = useState<Preview | null>(null);
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
    const handle = event.currentTarget;
    const id = handle.dataset.panel;
    const mode = handle.dataset.gesture as Gesture["mode"];
    const box = boxes.find((b) => b.id === id);
    if (!id || !box) return;
    event.preventDefault();
    // Capture: keep receiving moves even when the pointer leaves the handle.
    handle.setPointerCapture(event.pointerId);
    handle.style.cursor = mode === "move" ? "grabbing" : "nwse-resize";
    const { left, top } = toPixels(box, width);
    gesture.current = {
      id,
      mode,
      startX: event.clientX,
      startY: event.clientY,
      box,
      base: boxes,
      element: handle.parentElement,
      handle,
      left,
      top,
      cols: 0,
      rows: 0,
    };
    latest.current = boxes;
    setPreview({ boxes, id, mode, origin: { left, top } });
  }

  function onPointerMove(event: PointerEvent<HTMLElement>) {
    const g = gesture.current;
    if (!g) return;
    const dx = event.clientX - g.startX;
    const dy = event.clientY - g.startY;

    // 1. The dragged panel sticks to the pointer: straight to the DOM, no React render.
    if (g.mode === "move" && g.element) {
      const pixels = toPixels(g.box, width);
      const left = Math.min(Math.max(g.left + dx, 0), Math.max(width - pixels.width, 0));
      const top = Math.max(g.top + dy, 0);
      g.element.style.transform = translate(left, top);
    }

    // 2. The layout only changes when the pointer crosses into another cell.
    const { cols, rows } = toGridDelta(dx, dy, width);
    if (cols === g.cols && rows === g.rows) return;
    g.cols = cols;
    g.rows = rows;
    const next =
      g.mode === "move"
        ? moveBox(g.base, g.id, g.box.x + cols, g.box.y + rows)
        : resizeBox(g.base, g.id, g.box.w + cols, g.box.h + rows);
    latest.current = next;
    setPreview((current) => (current ? { ...current, boxes: next } : current));
  }

  // Let go: the panel glides from where the pointer left it into its cell.
  function finish(g: Gesture, finalBox: Box | undefined) {
    g.handle.style.cursor = g.mode === "move" ? "grab" : "nwse-resize";
    const element = g.element;
    if (g.mode !== "move" || !element || !finalBox) return;
    const { left, top } = toPixels(finalBox, width);
    element.style.transition = `transform ${LAND_MS}ms ${LAND_EASE}`;
    element.style.transform = translate(left, top);
    window.setTimeout(() => {
      element.style.transition = ""; // from here on the class decides
    }, LAND_MS + 30);
  }

  function onPointerUp() {
    const g = gesture.current;
    const next = latest.current;
    gesture.current = null;
    latest.current = null;
    setPreview(null);
    if (!g || !next) return;
    finish(g, next.find((b) => b.id === g.id));
    const changed = changedBoxes(g.base, next);
    if (changed.length) onCommit(next, changed);
  }

  function onPointerCancel() {
    const g = gesture.current;
    gesture.current = null; // e.g. the browser took over for scrolling: drop the gesture
    latest.current = null;
    setPreview(null);
    if (g) finish(g, g.box); // back to where it started
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
      // The browser took the pointer away without a pointerup (e.g. released outside the
      // window): finish like a normal release, so a panel can never stay stuck mid-drag.
      onLostPointerCapture: onPointerUp,
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
  const dragging = preview?.mode === "move";
  const target = dragging ? shown.find((b) => b.id === active) : undefined;

  return (
    <div
      ref={container}
      className={`relative ${canEdit ? "rounded-md outline-1 outline-offset-4 outline-ink/30 outline-dashed" : ""} ${preview ? "select-none" : ""}`}
      style={{ height: Math.max(gridHeight(shown), canEdit ? 200 : 0) }}
    >
      {width > 0 && target && (
        // Where the dragged panel will land, drawn under the panels.
        <div
          aria-hidden
          className="absolute top-0 left-0 z-0 rounded-md border-[1.5px] border-dashed border-ink/60 bg-ink/4 transition-transform duration-150 ease-out"
          style={(() => {
            const { left, top, width: w, height: h } = toPixels(target, width);
            return { transform: translate(left, top), width: w, height: h };
          })()}
        />
      )}
      {width > 0 &&
        shown.map((box) => {
          const { left, top, width: w, height: h } = toPixels(box, width);
          const moving = box.id === active;
          // The panel being dragged keeps its starting transform in React's eyes: the pointer
          // handler moves it by hand, and React must never overwrite that mid-gesture.
          const at = moving && dragging && preview ? preview.origin : { left, top };
          return (
            <div
              key={box.id}
              className={`absolute top-0 left-0 ${
                moving
                  ? "z-20 rounded-md shadow-hard-lg will-change-transform"
                  : `z-10 transition-transform duration-150 ease-out ${canEdit ? "will-change-transform" : ""}`
              }`}
              style={{ transform: translate(at.left, at.top), width: w, height: h }}
            >
              <PanelSlot id={box.id} editable={canEdit} renderPanel={renderPanel} />
              {canEdit && (
                // An invisible strip over the panel's header: grab it to move the panel. It stops
                // short of the right edge so the panel's menu button stays clickable.
                <span
                  {...handle(box.id, "move")}
                  aria-label="Move panel"
                  title="Drag to move"
                  className="absolute top-0 left-0 right-12 h-10"
                />
              )}
              {canEdit && (
                <span
                  {...handle(box.id, "resize")}
                  aria-label="Resize panel"
                  title="Drag to resize"
                  className="absolute right-1 bottom-1 h-4 w-4 rounded-br-sm border-r-2 border-b-2 border-ink/50 hover:border-ink"
                />
              )}
            </div>
          );
        })}
    </div>
  );
}
