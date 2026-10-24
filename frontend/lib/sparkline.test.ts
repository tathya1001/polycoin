import { describe, expect, it } from "vitest";
import { runPath, sparklineRuns } from "./sparkline";

describe("sparklineRuns", () => {
  it("spreads the points across the width, highest value at the top", () => {
    const [run] = sparklineRuns([0, 5, 10], 100, 30, 0);
    expect(run).toEqual([
      [0, 30],
      [50, 15],
      [100, 0],
    ]);
  });

  it("keeps the padding so a thick line isn't clipped", () => {
    const [run] = sparklineRuns([0, 10], 100, 30, 2);
    expect(run.map(([, y]) => y)).toEqual([28, 2]);
  });

  it("draws a flat series through the middle", () => {
    const [run] = sparklineRuns([7, 7, 7], 100, 30);
    expect(run.map(([, y]) => y)).toEqual([15, 15, 15]);
  });

  it("splits at a gap, so missing data is a gap in the line", () => {
    const runs = sparklineRuns([1, 2, null, 4, 5], 100, 30);
    expect(runs.map((run) => run.length)).toEqual([2, 2]);
  });

  it("puts a single point in the middle and shows nothing for no data", () => {
    expect(sparklineRuns([3], 100, 30)).toEqual([[[50, 15]]]);
    expect(sparklineRuns([], 100, 30)).toEqual([]);
    expect(sparklineRuns([null, null], 100, 30)).toEqual([]);
  });
});

describe("runPath", () => {
  it("writes a move then lines", () => {
    expect(runPath([[0, 30], [50, 15.04], [100, 0]])).toBe("M0.0 30.0 L50.0 15.0 L100.0 0.0");
  });

  it("gives a lone point a tick so it still shows", () => {
    expect(runPath([[50, 15]])).toBe("M49.0 15.0 L51.0 15.0");
  });
});
