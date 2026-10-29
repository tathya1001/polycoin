"use client";

import { Filter, X } from "lucide-react";

type Props = {
  label: string; // what was clicked, e.g. "Food"
  panelTitle: string; // where the click was
  onClear: () => void;
};

// Shown while a click on one panel is filtering the others. It is not saved: a reload clears it.
export default function SelectionBar({ label, panelTitle, onClear }: Props) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-2 rounded-md border-[1.5px] border-line bg-wash px-3 py-1.5 text-sm"
    >
      <Filter size={15} aria-hidden />
      <span>
        Other panels show <strong className="font-semibold">{label}</strong> only
        {panelTitle && <span className="text-ink-2"> (picked in {panelTitle})</span>}
      </span>
      <button
        type="button"
        onClick={onClear}
        className="ml-auto inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-medium underline decoration-dotted underline-offset-2 hover:bg-surface"
      >
        <X size={14} aria-hidden /> Clear
      </button>
    </div>
  );
}
