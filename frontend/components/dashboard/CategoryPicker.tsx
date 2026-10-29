"use client";

import { ChevronDown } from "lucide-react";
import type { Category } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";

const MAX_SELECTED = 20; // spec.MAX_CATEGORIES

type Props = {
  categories: Category[];
  selected: string[]; // category ids; empty means "all categories"
  onChange: (ids: string[]) => void;
  label?: string;
};

// A button that opens a checklist of categories (with their colour dots).
export default function CategoryPicker({ categories, selected, onChange, label = "Categories" }: Props) {
  const chosen = new Set(selected);
  const summary =
    selected.length === 0
      ? "All categories"
      : selected.length === 1
        ? (categories.find((c) => c.id === selected[0])?.name ?? "1 category")
        : `${selected.length} categories`;

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else if (next.size < MAX_SELECTED) next.add(id);
    onChange([...next]);
  }

  return (
    <Popover
      trigger={(p) => (
        <Button
          size="sm"
          aria-label={`${label}: ${summary}`}
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
        All categories
      </button>
      <div className="flex flex-col gap-1.5">
        {categories.map((category) => (
          <Checkbox
            key={category.id}
            checked={chosen.has(category.id)}
            onChange={() => toggle(category.id)}
            label={
              <span className="flex items-center gap-2">
                <span aria-hidden className="size-2.5 rounded-full border border-edge" style={{ backgroundColor: category.color }} />
                {category.name}
              </span>
            }
          />
        ))}
      </div>
    </Popover>
  );
}
