import { runPath, sparklineRuns } from "@/lib/sparkline";

// A KPI's trend line: plain SVG, stretched to fill its box. Decorative: the figures say the same.
export default function Sparkline({ values }: { values: (number | null)[] }) {
  const runs = sparklineRuns(values, 100, 30);
  if (runs.length === 0) return null;
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden className="h-full min-h-7 w-full overflow-visible">
      {runs.map((run, index) => (
        <path
          key={index}
          d={runPath(run)}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}
