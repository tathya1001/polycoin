import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatValue } from "@/lib/insights";
import type { PanelConfig, QueryResult } from "@/lib/types";

// One big number, plus the change from the previous period when the panel compares.
// Plain React, not ECharts: a number doesn't need a chart library.
export default function KpiPanel({ config, result }: { config: PanelConfig; result: QueryResult }) {
  const [value, previous, change] = result.rows[0] ?? [null, null, null];
  const changeNumber = change === null ? null : Number(change);

  // More spending is bad news; more income (or net, balance...) is good news.
  const upIsBad = config.y.measure === "spend";
  let tone = "bg-wash text-ink-2";
  if (changeNumber !== null && changeNumber !== 0) {
    tone = changeNumber > 0 === upIsBad ? "bg-[#fee2e2] text-neg" : "bg-[#dcfce7] text-pos";
  }
  const Arrow = changeNumber === null || changeNumber === 0 ? Minus : changeNumber > 0 ? ArrowUpRight : ArrowDownRight;

  return (
    <div className="flex h-full flex-col justify-center gap-2 px-2">
      <p className="text-[40px] leading-none font-semibold tracking-tight tabular-nums">{formatValue(value, config)}</p>
      {config.compare && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {changeNumber === null ? (
            <span className="text-ink-2">No previous period to compare</span>
          ) : (
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold", tone)}>
              <Arrow size={14} aria-hidden />
              {Math.abs(changeNumber)}%
            </span>
          )}
          {previous !== null && <span className="text-muted">vs {formatValue(previous, config)} before</span>}
        </p>
      )}
    </div>
  );
}
