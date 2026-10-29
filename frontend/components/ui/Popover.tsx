"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

type TriggerProps = {
  onClick: () => void;
  "aria-expanded": boolean;
  "aria-haspopup": "dialog";
};

// A small floating panel anchored under its trigger. Closes on Esc or a click outside.
// `trigger` receives the props to spread onto whatever button you want:
//   <Popover trigger={(p) => <Chip {...p}>Date</Chip>}>…</Popover>
export function Popover({
  trigger,
  children,
  align = "left",
  className,
}: {
  trigger: (props: TriggerProps & { open: boolean }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "left" | "right";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div ref={root} className="relative inline-block">
      {trigger({ open, onClick: () => setOpen((o) => !o), "aria-expanded": open, "aria-haspopup": "dialog" })}
      {open && (
        <div
          role="dialog"
          className={cn(
            "absolute top-full z-50 mt-2 min-w-56 animate-[pop-in_140ms_ease-out] rounded-md border-[1.5px] border-line bg-surface p-3 shadow-pop",
            align === "right" ? "right-0" : "left-0",
            className,
          )}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}
