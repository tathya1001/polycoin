import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  KPI_FIGURE_LABELS,
  baselineText,
  defaultKpi,
  formatBaseline,
  formatFigure,
  formatValue,
  kpiTone,
  type Tone,
} from "@/lib/insights";
import type { PanelConfig, QueryResult } from "@/lib/types";
import Sparkline from "./Sparkline";

const TONES: Record<Tone, string> = {
  good: "bg-pos-bg text-pos",
  bad: "bg-neg-bg text-neg",
  flat: "bg-wash text-ink-2",
};

// One big number, what it is compared with, small figures under it, and a trend line.
// Plain React, not ECharts: a number doesn't need a chart library.
export default function KpiPanel({ config, result }: { config: PanelConfig; result: QueryResult }) {
  const kpi = config.kpi ?? defaultKpi();
  const [value, previous, change] = result.rows[0] ?? [null, null, null];
  const changeNumber = change === null ? null : Number(change);
  const tone = kpiTone(changeNumber, kpi, config.y.measure);
  const Arrow = changeNumber === null || changeNumber === 0 ? Minus : changeNumber > 0 ? ArrowUpRight : ArrowDownRight;
  const trend = result.sparkline?.rows.map((row) => (row[1] === null ? null : Number(row[1])));

  return (
    <div className="flex h-full flex-col justify-center gap-1.5 px-2">
      {/* Proportional digits: tabular ones (for lining up columns) are a different, wider design
          of each digit in some fonts, Geist included, and make one big number look off. */}
      <p className="text-[40px] leading-none font-semibold tracking-tight">{formatValue(value, config)}</p>
      {kpi.compare !== "none" && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {changeNumber === null ? (
            <span className="text-ink-2">{previous === null ? "Nothing to compare with" : "No change to show"}</span>
          ) : (
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold", TONES[tone])}>
              <Arrow size={14} aria-hidden />
              {Math.abs(changeNumber)}%
            </span>
          )}
          {previous !== null && <span className="text-muted">{baselineText(kpi, formatBaseline(previous, config))}</span>}
        </p>
      )}
      {result.secondary && result.secondary.length > 0 && (
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] text-ink-2">
          {result.secondary.map((figure) => (
            <span key={figure.id}>
              {KPI_FIGURE_LABELS[figure.id]}{" "}
              <strong className="font-semibold text-ink">{formatFigure(figure.id, figure.value)}</strong>
            </span>
          ))}
        </p>
      )}
      {trend && trend.length > 0 && (
        <div className="mt-1 min-h-7 flex-1 text-ink-2">
          <Sparkline values={trend} />
        </div>
      )}
    </div>
  );
}
