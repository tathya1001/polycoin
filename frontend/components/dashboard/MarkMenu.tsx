"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type MarkAction = { id: string; label: string; icon: ReactNode; run: () => void };

type Props = {
  at: { x: number; y: number }; // where the click happened, in viewport pixels
  title: string; // what was clicked
  actions: MarkAction[];
  onClose: () => void;
};

const MARGIN = 8;

// The small menu that opens on a clicked mark. It is drawn on the page body, not inside the
// panel: a panel clips what overflows it, and a menu near its edge would be cut off.
export default function MarkMenu({ at, title, actions, onClose }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState({ left: at.x, top: at.y });

  // Keep the whole menu on screen: measure it once it exists, then shift it back from the edges.
  useLayoutEffect(() => {
    const box = root.current?.getBoundingClientRect();
    if (!box) return;
    setPlace({
      left: Math.max(MARGIN, Math.min(at.x, window.innerWidth - box.width - MARGIN)),
      top: Math.max(MARGIN, Math.min(at.y, window.innerHeight - box.height - MARGIN)),
    });
  }, [at.x, at.y]);

  useEffect(() => {
    root.current?.querySelector<HTMLElement>("button")?.focus();
    const onPointerDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onClose, true); // a menu that stays put while the page moves is lost
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [onClose]);

  // Up and down move between the items, as in any menu.
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = [...(root.current?.querySelectorAll<HTMLElement>("button") ?? [])];
    const next = items.indexOf(document.activeElement as HTMLElement) + (e.key === "ArrowDown" ? 1 : -1);
    items[(next + items.length) % items.length]?.focus();
  }

  return createPortal(
    <div
      ref={root}
      role="menu"
      aria-label={title ? `Actions for ${title}` : "Actions"}
      onKeyDown={onKeyDown}
      style={{ left: place.left, top: place.top }}
      className="fixed z-50 w-60 animate-[pop-in_140ms_ease-out] rounded-md border-[1.5px] border-line bg-surface p-1.5 text-sm shadow-pop"
    >
      {title && <p className="truncate px-2.5 pt-1 pb-1.5 text-xs font-semibold text-ink-2 uppercase">{title}</p>}
      {actions.map((action) => (
        <button
          key={action.id}
          type="button"
          role="menuitem"
          onClick={() => {
            onClose();
            action.run();
          }}
          className="flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-left hover:bg-wash focus-visible:bg-wash"
        >
          {action.icon}
          {action.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}
