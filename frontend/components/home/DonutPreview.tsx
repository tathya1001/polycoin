import { SAMPLE_GROUPS } from "@/lib/sampleYear";
import { markStyle } from "./PreviewParts";

const CENTRE = 100;
// The dashboards' donut is 45% to 70% of the space: the same ring, scaled to fill this box.
const OUTER = 96;
const INNER = (OUTER * 45) / 70;

function point(radius: number, angle: number): string {
  return `${(CENTRE + radius * Math.cos(angle)).toFixed(2)} ${(CENTRE + radius * Math.sin(angle)).toFixed(2)}`;
}

// One slice of the ring, from angle `start` to `end` (radians, clockwise from 3 o'clock).
function slice(start: number, end: number): string {
  const large = end - start > Math.PI ? 1 : 0;
  return (
    `M${point(OUTER, start)}A${OUTER} ${OUTER} 0 ${large} 1 ${point(OUTER, end)}` +
    `L${point(INNER, end)}A${INNER} ${INNER} 0 ${large} 0 ${point(INNER, start)}Z`
  );
}

// A donut chart of the year's spend per group, starting at 12 o'clock. Plain SVG; the slice edges
// follow the colour mode like the dashboards' donuts do (globals.css, .preview-slice).
export function DonutPreview({ totals }: { totals: number[] }) {
  const sum = totals.reduce((total, value) => total + value, 0) || 1;
  // Where each slice ends, as a share of the circle: the running total of the shares.
  const ends = totals.map((_, index) => totals.slice(0, index + 1).reduce((total, value) => total + value, 0) / sum);
  const angle = (share: number) => share * 2 * Math.PI - Math.PI / 2;
  return (
    <svg viewBox="0 0 200 200" className="w-full max-w-40 shrink overflow-visible">
      {SAMPLE_GROUPS.map((group, index) => (
        <path
          key={group.name}
          d={slice(angle(index ? ends[index - 1] : 0), angle(ends[index]))}
          className="series-mark preview-slice fill-(--mark)"
          style={markStyle(group.color)}
        />
      ))}
    </svg>
  );
}
