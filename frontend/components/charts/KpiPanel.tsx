import { formatValue } from "@/lib/insights";
import type { PanelConfig, QueryResult } from "@/lib/types";

// One big number, plus the change from the previous period when the panel compares.
// Plain React, not ECharts: a number doesn't need a chart library.
export default function KpiPanel({ config, result }: { config: PanelConfig; result: QueryResult }) {
  const [value, previous, change] = result.rows[0] ?? [null, null, null];
  const changeNumber = change === null ? null : Number(change);

  // More spending is bad news; more income (or net, balance...) is good news.
  const upIsBad = config.y.measure === "spend";
  let tone = "text-gray-500";
  if (changeNumber !== null && changeNumber !== 0) {
    tone = changeNumber > 0 === upIsBad ? "text-red-600" : "text-green-600";
  }

  return (
    <div className="flex h-full flex-col justify-center gap-1 px-1">
      <p className="text-3xl font-semibold tabular-nums">{formatValue(value, config)}</p>
      {config.compare && (
        <p className={`text-sm ${tone}`}>
          {changeNumber === null
            ? "No previous period to compare"
            : `${changeNumber > 0 ? "▲" : changeNumber < 0 ? "▼" : "■"} ${Math.abs(changeNumber)}%`}
          {previous !== null && (
            <span className="text-gray-500"> vs {formatValue(previous, config)} before</span>
          )}
        </p>
      )}
    </div>
  );
}
