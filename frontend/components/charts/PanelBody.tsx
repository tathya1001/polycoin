"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { isError } from "@/lib/insights";
import type { PanelConfig, QueryOutcome } from "@/lib/types";
import KpiPanel from "./KpiPanel";
import { isEmptyResult, toOption, type ChartKeys } from "./toOption";

// ECharts needs the browser, so it is only loaded on the client, and only once a chart shows.
const EChart = dynamic(() => import("./EChart"), {
  ssr: false,
  loading: () => <Message>Drawing…</Message>,
});

function Message({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "error" }) {
  return (
    <div className="flex h-full items-center justify-center p-2 text-center text-sm">
      <p className={tone === "error" ? "text-red-600" : "text-gray-500"}>{children}</p>
    </div>
  );
}

type Props = {
  config: PanelConfig | null;
  outcome: QueryOutcome | undefined; // undefined: not queried yet
  loading: boolean;
  // A click on the chart, already translated into the backend's raw x / colour values.
  onPick?: (picked: { x: ChartKeys["x"][number]; color?: ChartKeys["colors"][number] }) => void;
};

// What goes inside a panel: the chart, or a loading / empty / error message instead.
export default function PanelBody({ config, outcome, loading, onPick }: Props) {
  const built = useMemo(
    () => (config && outcome && !isError(outcome) ? toOption(config, outcome) : null),
    [config, outcome],
  );

  if (!config) return <Message tone="error">This panel&apos;s settings no longer work. Edit it to fix them.</Message>;
  if (!outcome) return <Message>{loading ? "Loading…" : "Not loaded yet."}</Message>;
  if (isError(outcome)) return <Message tone="error">{outcome.error.detail}</Message>;
  if (isEmptyResult(config, outcome)) return <Message>No transactions in this period.</Message>;
  if (config.chart === "kpi") return <KpiPanel config={config} result={outcome} />;
  if (!built) return null;

  const keys = built.keys;
  return (
    <div className={`h-full w-full transition-opacity ${loading ? "opacity-50" : ""}`}>
      <EChart
        option={built.option}
        onPick={
          onPick && keys
            ? (seriesIndex, dataIndex) =>
                onPick({ x: keys.x[dataIndex], color: keys.colors.length ? keys.colors[seriesIndex] : undefined })
            : undefined
        }
      />
    </div>
  );
}
