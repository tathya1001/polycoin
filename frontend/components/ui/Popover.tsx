"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";

const PANEL_WIDTH = 256; // a floating panel's w-64
const PANEL_GAP = 8;
const PAGE_GUTTER = 16;

type TriggerProps = {
  onClick: (event?: { currentTarget: Element }) => void;
  "aria-expanded": boolean;
  "aria-haspopup": "dialog";
};

// A small floating panel anchored under its trigger. Closes on Esc or a click outside.
// `trigger` receives the props to spread onto whatever button you want:
//   <Popover trigger={(p) => <Chip {...p}>Date</Chip>}>…</Popover>
// `floating` draws the panel over the whole page, for a trigger inside a scrolling box that would
// clip it. It closes when the page scrolls, because it would otherwise drift off its trigger.
export function Popover({
  trigger,
  children,
  align = "left",
  className,
  floating = false,
}: {
  trigger: (props: TriggerProps & { open: boolean }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "left" | "right";
  className?: string;
  floating?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({});
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  function toggle(event?: { currentTarget: Element }) {
    if (floating && !open && event) {
      const box = event.currentTarget.getBoundingClientRect();
      const widest = window.innerWidth - PANEL_WIDTH - PAGE_GUTTER;
      setPosition({
        top: box.bottom + PANEL_GAP,
        left: Math.max(PAGE_GUTTER, Math.min(box.left, widest)),
        width: PANEL_WIDTH,
      });
    }
    setOpen((o) => !o);
  }

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (root.current && !root.current.contains(target) && !panel.current?.contains(target)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      // The panel held the focus and is about to go, so hand it back to the trigger.
      if (floating) root.current?.querySelector("button")?.focus();
    };
    // A scroll inside the panel itself (a long checklist) is fine; any other one moves the trigger.
    const onScroll = (e: Event) => {
      if (floating && !panel.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open, floating]);

  const close = () => setOpen(false);
  const look =
    "z-50 min-w-56 animate-[pop-in_140ms_ease-out] rounded-md border-[1.5px] border-line bg-surface p-3 shadow-pop";
  const body = typeof children === "function" ? children(close) : children;

  return (
    <div ref={root} className="relative inline-block">
      {trigger({ open, onClick: toggle, "aria-expanded": open, "aria-haspopup": "dialog" })}
      {open &&
        (floating ? (
          createPortal(
            <div ref={panel} role="dialog" style={position} className={cn("fixed", look, className)}>
              {body}
            </div>,
            document.body,
          )
        ) : (
          <div
            ref={panel}
            role="dialog"
            className={cn("absolute top-full mt-2", align === "right" ? "right-0" : "left-0", look, className)}
          >
            {body}
          </div>
        ))}
    </div>
  );
}
