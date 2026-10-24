"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { isError } from "@/lib/insights";
import { isText, type AnyPanelConfig, type Picked, type QueryOutcome } from "@/lib/types";
import KpiPanel from "./KpiPanel";
import TextPanel from "./TextPanel";
import { isEmptyResult, toOption, type CategoryColors, type Highlight } from "./toOption";

// ECharts needs the browser, so it is only loaded on the client, and only once a chart shows.
const EChart = dynamic(() => import("./EChart"), {
  ssr: false,
  loading: () => <Message>Drawing…</Message>,
});

function Message({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "error" }) {
  return (
    <div className="flex h-full items-center justify-center p-2 text-center text-sm">
      <p className={tone === "error" ? "font-medium text-neg" : "text-muted"}>{children}</p>
    </div>
  );
}

type Props = {
  config: AnyPanelConfig | null;
  outcome: QueryOutcome | undefined; // undefined: not queried yet
  loading: boolean;
  categoryColors?: CategoryColors; // each category's default colour
  // A click on the chart, already translated into the backend's raw values, and where it
  // happened (pixels from the chart's top-left corner).
  onPick?: (picked: Picked, at: { x: number; y: number }) => void;
  // A click on a KPI card, which has no marks to pick from.
  onOpen?: () => void;
  // The x value to leave undimmed because it filters the other panels.
  highlight?: Highlight;
};

// What goes inside a panel: the chart, or a loading / empty / error message instead.
export default function PanelBody({ config, outcome, loading, categoryColors, onPick, onOpen, highlight }: Props) {
  const built = useMemo(
    () =>
      config && !isText(config) && outcome && !isError(outcome)
        ? toOption(config, outcome, categoryColors, highlight)
        : null,
    [config, outcome, categoryColors, highlight],
  );

  if (!config) return <Message tone="error">This panel&apos;s settings no longer work. Edit it to fix them.</Message>;
  if (isText(config)) return <TextPanel text={config.text} />; // a note has no query
  if (!outcome) return <Message>{loading ? "Loading…" : "Not loaded yet."}</Message>;
  if (isError(outcome)) return <Message tone="error">{outcome.error.detail}</Message>;
  if (isEmptyResult(config, outcome)) {
    // A calculated field can have transactions but no answer, e.g. when it divides by zero.
    const formulaBlank = config.y.measure === "formula" && outcome.rows.length > 0;
    return <Message>{formulaBlank ? "The formula has no value here (it may divide by zero)." : "No transactions in this period."}</Message>;
  }
  if (config.chart === "kpi") {
    const card = <KpiPanel config={config} result={outcome} />;
    if (!onOpen) return card;
    return (
      <button
        type="button"
        onClick={onOpen}
        title="Show the transactions behind this number"
        className="block h-full w-full cursor-pointer rounded-sm text-left hover:bg-canvas/60"
      >
        {card}
      </button>
    );
  }
  if (!built) return null;

  const keys = built.keys;
  return (
    <div className={`h-full w-full transition-opacity ${loading ? "opacity-50" : ""}`}>
      <EChart
        option={built.option}
        onPick={
          onPick && keys
            ? (seriesIndex, dataIndex, at) => {
                const cell = keys.cells?.[dataIndex];
                if (cell) return onPick({ x: cell.x, row: cell.row }, at);
                onPick({ x: keys.x[dataIndex], color: keys.colors.length ? keys.colors[seriesIndex] : undefined }, at);
              }
            : undefined
        }
      />
    </div>
  );
}
