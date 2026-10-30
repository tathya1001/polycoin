"use client";

// What opens from a column header. Text and numbers wait for a pause in typing, because each
// change searches encrypted rows on the server. Dates and checklists apply at once.

import { useEffect, useRef, useState } from "react";
import { Checkbox, Field, Input, Select } from "@/components/ui/Field";
import type { TxnType } from "@/lib/transactionFilters";

const TYPING_PAUSE_MS = 400;

// A value kept while typing, and passed on after a pause. A change from outside (a chip removed,
// Clear filters) shows at once. Closing the panel mid-pause still applies what was typed.
function usePausedValue(value: string, onChange: (value: string) => void) {
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  const timer = useRef<number | undefined>(undefined);
  const waiting = useRef<(() => void) | null>(null);

  if (value !== seen) {
    setSeen(value);
    setDraft(value);
  }

  function flush() {
    window.clearTimeout(timer.current);
    const send = waiting.current;
    waiting.current = null;
    send?.();
  }

  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
      waiting.current?.();
    },
    [],
  );

  function change(next: string) {
    setDraft(next);
    window.clearTimeout(timer.current);
    waiting.current = () => onChange(next);
    timer.current = window.setTimeout(flush, TYPING_PAUSE_MS);
  }

  return { draft, change, flush };
}

function PausedInput({
  label,
  value,
  onChange,
  ...rest
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
} & Omit<React.ComponentProps<typeof Input>, "value" | "onChange">) {
  const { draft, change, flush } = usePausedValue(value, onChange);
  return (
    <Field label={label}>
      <Input
        dense
        value={draft}
        onChange={(e) => change(e.target.value)}
        onBlur={flush}
        onKeyDown={(e) => e.key === "Enter" && flush()}
        {...rest}
      />
    </Field>
  );
}

export function TextFilter({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return <PausedInput label={label} value={value} onChange={onChange} maxLength={100} autoFocus />;
}

export function DateFilter({
  from,
  to,
  onChange,
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-2">
      <Field label="From">
        <Input dense type="date" value={from} max={to || undefined} onChange={(e) => onChange(e.target.value, to)} />
      </Field>
      <Field label="To">
        <Input dense type="date" value={to} min={from || undefined} onChange={(e) => onChange(from, e.target.value)} />
      </Field>
    </div>
  );
}

export function RangeFilter({
  low,
  high,
  onChange,
}: {
  low: string;
  high: string;
  onChange: (low: string, high: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <PausedInput label="From" type="number" step="any" value={low} onChange={(next) => onChange(next, high)} />
      <PausedInput label="To" type="number" step="any" value={high} onChange={(next) => onChange(low, next)} />
    </div>
  );
}

export function AmountFilter({
  type,
  low,
  high,
  onType,
  onRange,
}: {
  type: TxnType;
  low: string;
  high: string;
  onType: (type: TxnType) => void;
  onRange: (low: string, high: string) => void;
}) {
  return (
    <div className="space-y-3">
      <Field label="Show">
        <Select dense className="w-full" value={type} onChange={(e) => onType(e.target.value as TxnType)}>
          <option value="">Money in and out</option>
          <option value="credit">Money in</option>
          <option value="debit">Money out</option>
        </Select>
      </Field>
      <RangeFilter low={low} high={high} onChange={onRange} />
    </div>
  );
}

export function Checklist({
  items,
  selected,
  allLabel,
  onChange,
}: {
  items: { id: string; name: string; color: string }[];
  selected: string[];
  allLabel: string;
  onChange: (ids: string[]) => void;
}) {
  const chosen = new Set(selected);

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange([...next]);
  }

  return (
    <div className="space-y-2">
      <button type="button" className="text-xs font-medium underline underline-offset-2" onClick={() => onChange([])}>
        {allLabel}
      </button>
      <div className="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
        {items.map((item) => (
          <Checkbox
            key={item.id}
            checked={chosen.has(item.id)}
            onChange={() => toggle(item.id)}
            label={
              <span className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="size-2.5 shrink-0 rounded-full border border-edge"
                  style={{ backgroundColor: item.color }}
                />
                {item.name}
              </span>
            }
          />
        ))}
      </div>
    </div>
  );
}
