"use client";

import { ChevronDown } from "lucide-react";
import type { DataSource } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";

type Props = {
  sources: DataSource[];
  selected: string[]; // data source ids; empty means "all"
  onChange: (ids: string[]) => void;
  allLabel?: string;
};

// A button that opens a checklist of data sources. With only one source there is nothing to
// choose, so it shows nothing.
export default function SourcePicker({ sources, selected, onChange, allLabel = "All data sources" }: Props) {
  if (sources.length < 2) return null;
  const chosen = new Set(selected);
  const summary =
    selected.length === 0
      ? allLabel
      : selected.length === 1
        ? (sources.find((s) => s.id === selected[0])?.name ?? "1 data source")
        : `${selected.length} data sources`;

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange([...next]);
  }

  return (
    <Popover
      trigger={(p) => (
        <Button
          size="sm"
          aria-label={`Data sources: ${summary}`}
          onClick={p.onClick}
          aria-expanded={p["aria-expanded"]}
          aria-haspopup={p["aria-haspopup"]}
        >
          {summary}
          <ChevronDown size={14} aria-hidden />
        </Button>
      )}
      className="max-h-72 w-60 overflow-auto"
    >
      <button type="button" className="mb-2 text-xs font-medium underline underline-offset-2" onClick={() => onChange([])}>
        {allLabel}
      </button>
      <div className="flex flex-col gap-1.5">
        {sources.map((source) => (
          <Checkbox
            key={source.id}
            checked={chosen.has(source.id)}
            onChange={() => toggle(source.id)}
            label={
              <span className="flex items-center gap-2">
                <span aria-hidden className="size-2.5 rounded-full border border-edge" style={{ backgroundColor: source.color }} />
                {source.name}
              </span>
            }
          />
        ))}
      </div>
    </Popover>
  );
}
