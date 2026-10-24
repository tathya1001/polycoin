"use client";

import { Fragment, useCallback, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import PanelBody from "@/components/charts/PanelBody";
import type { CategoryColors, Highlight } from "@/components/charts/toOption";
import type { AnyPanelConfig, Picked, QueryOutcome } from "@/lib/types";
import MarkMenu, { type MarkAction } from "./MarkMenu";

type Props = {
  config: AnyPanelConfig | null;
  outcome: QueryOutcome | undefined;
  loading: boolean;
  categoryColors: CategoryColors;
  highlight: Highlight;
  title: string; // the panel's own name, the first step of the drill path
  trail: string[]; // what was drilled into, outermost first
  onTrail: (depth: number) => void; // keep the first `depth` steps of the trail
  interactive: boolean; // false while the dashboard is being edited
  actionsFor: (picked: Picked) => MarkAction[]; // what a click on this mark can do
  labelFor: (picked: Picked) => string;
  onOpen?: () => void; // a click on a KPI card
};

// A panel's chart, with the menu a click opens and the path of a drill-down above it.
export default function PanelView({
  config,
  outcome,
  loading,
  categoryColors,
  highlight,
  title,
  trail,
  onTrail,
  interactive,
  actionsFor,
  labelFor,
  onOpen,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState<{ picked: Picked; at: { x: number; y: number } } | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);

  function pick(picked: Picked, at: { x: number; y: number }) {
    const origin = box.current?.getBoundingClientRect();
    if (!origin) return;
    setMenu({ picked, at: { x: origin.left + at.x, y: origin.top + at.y } });
  }

  const actions = menu ? actionsFor(menu.picked) : [];

  return (
    <div className="flex h-full flex-col">
      {trail.length > 0 && (
        <nav aria-label="Drill path" className="mb-1 flex flex-wrap items-center gap-x-1 text-[13px]">
          {[title || "Panel", ...trail].map((step, index, steps) => (
            <Fragment key={index}>
              {index > 0 && <ChevronRight size={13} className="text-muted" aria-hidden />}
              {index === steps.length - 1 ? (
                <span className="max-w-40 truncate font-semibold" aria-current="location">
                  {step}
                </span>
              ) : (
                <button
                  type="button"
                  className="max-w-40 truncate text-ink-2 underline decoration-dotted underline-offset-2 hover:text-ink"
                  onClick={() => onTrail(index)}
                >
                  {step}
                </button>
              )}
            </Fragment>
          ))}
        </nav>
      )}
      <div ref={box} className="min-h-0 flex-1">
        <PanelBody
          config={config}
          outcome={outcome}
          loading={loading}
          categoryColors={categoryColors}
          highlight={highlight}
          onPick={interactive ? pick : undefined}
          onOpen={interactive ? onOpen : undefined}
        />
      </div>
      {menu && actions.length > 0 && (
        <MarkMenu at={menu.at} title={labelFor(menu.picked)} actions={actions} onClose={closeMenu} />
      )}
    </div>
  );
}
