// The geometry of a KPI's trend line. Pure, so it is tested without a browser; the component
// only draws what this returns.

export type Point = [number, number];

/**
 * The line as runs of points inside a width x height box (y grows downwards, as in SVG).
 * A missing value (null) ends the run, so a gap in the data is a gap in the line. A flat series
 * is drawn through the middle; a single point is a run of one.
 */
export function sparklineRuns(values: (number | null)[], width: number, height: number, pad = 2): Point[][] {
  const known = values.filter((v): v is number => v !== null);
  if (known.length === 0) return [];
  const low = Math.min(...known);
  const high = Math.max(...known);
  const span = high - low;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const y = (value: number) => (span === 0 ? height / 2 : pad + (1 - (value - low) / span) * (height - 2 * pad));

  const runs: Point[][] = [];
  let current: Point[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (current.length) runs.push(current);
      current = [];
    } else {
      current.push([values.length > 1 ? index * step : width / 2, y(value)]);
    }
  });
  if (current.length) runs.push(current);
  return runs;
}

/** SVG path data for one run; a single point becomes a tiny horizontal tick so it still shows. */
export function runPath(run: Point[]): string {
  const points = run.length === 1 ? [[run[0][0] - 1, run[0][1]], [run[0][0] + 1, run[0][1]]] : run;
  return points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
}
