"use client";

import { COMPARISON_LABELS, GRANULARITY_LABELS, MEASURE_LABELS, PARAMETER_LABELS } from "@/lib/insights";
import type { Catalogue, DashboardParameters, ParameterName } from "@/lib/types";
import { Field, Input, Select } from "@/components/ui/Field";

// The dashboard's parameters: one control for each that some panel follows, none for the rest.
// A change applies at once (the panels re-run) and is saved with the dashboard.
export default function ParameterBar({
  catalogue,
  parameters,
  used,
  onChange,
}: {
  catalogue: Catalogue;
  parameters: DashboardParameters;
  used: ParameterName[];
  onChange: (next: DashboardParameters) => void;
}) {
  if (used.length === 0) return null;
  const [low, high] = catalogue.parameters.top_n;
  const date = catalogue.dimensions.find((d) => d.id === "date");

  return (
    <div
      className="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-md bg-surface px-4 py-3"
      aria-label="Dashboard parameters"
    >
      <span className="pb-2 text-[13px] font-semibold tracking-wide text-ink-2 uppercase">Parameters</span>
      {used.includes("top_n") && (
        <Field label={PARAMETER_LABELS.top_n} className="w-24">
          <Input
            dense
            type="number"
            min={low}
            max={high}
            value={parameters.top_n}
            onChange={(e) => {
              const value = e.target.valueAsNumber;
              if (Number.isInteger(value) && value >= low && value <= high) onChange({ ...parameters, top_n: value });
            }}
          />
        </Field>
      )}
      {used.includes("granularity") && (
        <Field label={PARAMETER_LABELS.granularity} className="w-36">
          <Select
            dense
            className="w-full"
            value={parameters.granularity}
            onChange={(e) => onChange({ ...parameters, granularity: e.target.value as DashboardParameters["granularity"] })}
          >
            {(date?.granularities ?? []).map((step) => (
              <option key={step} value={step}>
                {GRANULARITY_LABELS[step]}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {used.includes("measure") && (
        <Field label={PARAMETER_LABELS.measure} className="w-36">
          <Select
            dense
            className="w-full"
            value={parameters.measure}
            onChange={(e) => onChange({ ...parameters, measure: e.target.value as DashboardParameters["measure"] })}
          >
            {catalogue.parameters.measures.map((measure) => (
              <option key={measure} value={measure}>
                {MEASURE_LABELS[measure]}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {used.includes("comparison") && (
        <Field label={PARAMETER_LABELS.comparison} className="w-60">
          <Select
            dense
            className="w-full"
            value={parameters.comparison}
            onChange={(e) => onChange({ ...parameters, comparison: e.target.value as DashboardParameters["comparison"] })}
          >
            {catalogue.parameters.comparisons.map((comparison) => (
              <option key={comparison} value={comparison}>
                {COMPARISON_LABELS[comparison]}
              </option>
            ))}
          </Select>
        </Field>
      )}
    </div>
  );
}
