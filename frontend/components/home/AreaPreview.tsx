import { compactNumber } from "@/lib/format";
import { axisTicks, SAMPLE_GROUPS } from "@/lib/sampleYear";
import { markStyle } from "./PreviewParts";

const MONTH_INITIALS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

// A stacked area chart, drawn the way the dashboards draw one: straight lines, each with a light
// fill down to the series under it. Plain SVG, no chart library. The plot stretches to its box
// (the lines keep their width), and the axis labels are HTML, so they stay readable at any width.
export function AreaPreview({ byGroup }: { byGroup: number[][] }) {
  const months = byGroup[0].length;
  // stacks[group][month]: the top of that group's band.
  const stacks = byGroup.map((_, group) =>
    byGroup[0].map((__, month) => byGroup.slice(0, group + 1).reduce((total, series) => total + series[month], 0)),
  );
  const ticks = axisTicks(Math.max(...stacks[stacks.length - 1]));
  const top = ticks[ticks.length - 1] || 1;
  const x = (month: number) => (month / (months - 1)) * 100;
  const y = (value: number) => 100 - (value / top) * 100;
  const points = (values: number[]) => values.map((value, month) => `${x(month)} ${y(value)}`);

  return (
    <div className="grid h-full grid-cols-[auto_minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] gap-x-2 gap-y-1.5 text-xs text-ink-2">
      <div className="relative w-9">
        {ticks.map((value) => (
          <span key={value} className="absolute right-0 -translate-y-1/2 tabular-nums" style={{ top: `${y(value)}%` }}>
            {value ? `₹${compactNumber(value)}` : "0"}
          </span>
        ))}
      </div>
      <div className="relative">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible">
          {ticks.map((value) => (
            <line
              key={value}
              x1={0}
              x2={100}
              y1={y(value)}
              y2={y(value)}
              vectorEffect="non-scaling-stroke"
              className={value ? "stroke-hairline" : "stroke-line"}
              strokeWidth={value ? 1 : 1.5}
            />
          ))}
        </svg>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="preview-reveal absolute inset-0 size-full overflow-visible">
          {SAMPLE_GROUPS.map((group, index) => {
            const upper = points(stacks[index]);
            const lower = index ? points(stacks[index - 1]).reverse() : [`100 100`, `0 100`];
            return (
              <g key={group.name} className="series-mark" style={markStyle(group.color)}>
                <path d={`M${upper.join("L")}L${lower.join("L")}Z`} className="fill-(--mark)" fillOpacity={0.28} />
                <path
                  d={`M${upper.join("L")}`}
                  fill="none"
                  className="stroke-(--mark)"
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            );
          })}
        </svg>
      </div>
      <span />
      <div className="relative h-4">
        {MONTH_INITIALS.slice(0, months).map((initial, month) => (
          <span key={month} className="absolute -translate-x-1/2" style={{ left: `${x(month)}%` }}>
            {initial}
          </span>
        ))}
      </div>
    </div>
  );
}
