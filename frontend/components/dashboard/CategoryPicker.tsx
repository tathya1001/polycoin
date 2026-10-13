"use client";

import type { Category } from "@/lib/types";

const MAX_SELECTED = 20; // spec.MAX_CATEGORIES

type Props = {
  categories: Category[];
  selected: string[]; // category ids; empty means "all categories"
  onChange: (ids: string[]) => void;
  label?: string;
};

// A dropdown of checkboxes. <details> gives open / close and keyboard support for free.
export default function CategoryPicker({ categories, selected, onChange, label = "Categories" }: Props) {
  const chosen = new Set(selected);
  const summary =
    selected.length === 0
      ? "All categories"
      : selected.length === 1
        ? categories.find((c) => c.id === selected[0])?.name ?? "1 category"
        : `${selected.length} categories`;

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else if (next.size < MAX_SELECTED) next.add(id);
    onChange([...next]);
  }

  return (
    <div className="flex flex-col gap-1 text-sm">
      <span className="text-xs text-gray-500">{label}</span>
      <details className="relative">
        <summary className="cursor-pointer list-none border p-1 pr-6">{summary} ▾</summary>
        <div className="absolute left-0 top-full z-30 mt-1 max-h-64 w-56 overflow-auto rounded-md border border-gray-200 bg-background p-2 shadow-lg dark:border-gray-800">
          <button className="mb-1 text-xs underline" onClick={() => onChange([])}>
            All categories
          </button>
          {categories.map((category) => (
            <label key={category.id} className="flex items-center gap-2 py-0.5">
              <input type="checkbox" checked={chosen.has(category.id)} onChange={() => toggle(category.id)} />
              {category.name}
            </label>
          ))}
        </div>
      </details>
    </div>
  );
}
