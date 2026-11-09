import { describe, expect, it } from "vitest";
import {
  axisTicks,
  groupMonthTotals,
  groupTotals,
  monthTotals,
  percentChange,
  SAMPLE_GROUPS,
  sampleKpi,
  sampleYear,
} from "./sampleYear";

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);

describe("sampleYear", () => {
  it("gives the same year for the same seed, and another for another seed", () => {
    expect(sampleYear(2025, 7)).toEqual(sampleYear(2025, 7));
    expect(sampleYear(2025, 7)).not.toEqual(sampleYear(2025, 8));
  });

  it("has one entry per day, in order, from 1 January", () => {
    const year = sampleYear(2025);
    expect(year).toHaveLength(365);
    expect(year[0].date).toBe("2025-01-01");
    expect(year.at(-1)?.date).toBe("2025-12-31");
    expect(sampleYear(2024)).toHaveLength(366);
    expect(sampleYear(2024)[59].date).toBe("2024-02-29");
  });

  it("spends whole, non-negative rupees in every group", () => {
    for (const day of sampleYear()) {
      expect(day.amounts).toHaveLength(SAMPLE_GROUPS.length);
      for (const amount of day.amounts) {
        expect(Number.isInteger(amount)).toBe(true);
        expect(amount).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("pays rent on the 1st of every month and on no other day", () => {
    const rentDays = sampleYear().filter((day) => day.amounts[0] > 0);
    expect(rentDays.map((day) => day.date.slice(8))).toEqual(Array(12).fill("01"));
  });
});

describe("totals", () => {
  const year = sampleYear();

  it("agree with each other: groups make up months, months make up the year", () => {
    const byGroup = groupMonthTotals(year);
    const byMonth = monthTotals(year);
    const yearTotal = sum(year.map((day) => sum(day.amounts)));
    expect(byGroup).toHaveLength(SAMPLE_GROUPS.length);
    byMonth.forEach((total, month) => expect(sum(byGroup.map((group) => group[month]))).toBe(total));
    expect(sum(byMonth)).toBe(yearTotal);
    expect(sum(groupTotals(year))).toBe(yearTotal);
  });

  it("show the festival season: October spends more than September", () => {
    const byMonth = monthTotals(year);
    expect(byMonth[9]).toBeGreaterThan(byMonth[8]);
  });
});

describe("percentChange", () => {
  it("rounds to one decimal, up and down", () => {
    expect(percentChange(110, 100)).toBe(10);
    expect(percentChange(90, 100)).toBe(-10);
    expect(percentChange(1, 3)).toBe(-66.7);
  });

  it("is null with nothing to compare with", () => {
    expect(percentChange(50, 0)).toBeNull();
  });
});

describe("axisTicks", () => {
  it("uses round steps that reach the maximum", () => {
    expect(axisTicks(113_000)).toEqual([0, 50_000, 100_000, 150_000]);
    expect(axisTicks(78_000)).toEqual([0, 20_000, 40_000, 60_000, 80_000]);
    expect(axisTicks(100)).toEqual([0, 25, 50, 75, 100]);
  });

  it("is a single line for an empty chart", () => {
    expect(axisTicks(0)).toEqual([0]);
    expect(axisTicks(Number.NaN)).toEqual([0]);
  });
});

describe("sampleKpi", () => {
  const year = sampleYear();
  const byMonth = monthTotals(year);

  it("answers like the server does for a Number panel", () => {
    const { config, result } = sampleKpi(year, 8);
    expect(config.chart).toBe("kpi");
    expect(config.kpi?.compare).toBe("previous");
    expect(result.columns).toEqual(["value", "previous", "change_pct"]);
    expect(result.rows).toEqual([[byMonth[8], byMonth[7], percentChange(byMonth[8], byMonth[7])]]);
    expect(result.period).toEqual({ from: "2025-09-01", to: "2025-09-30" });
  });

  it("draws the trend from January to the month shown", () => {
    const { result } = sampleKpi(year, 8);
    expect(result.sparkline?.rows).toHaveLength(9);
    expect(result.sparkline?.rows[0]).toEqual(["2025-01-01", byMonth[0]]);
    expect(result.sparkline?.rows.at(-1)).toEqual(["2025-09-01", byMonth[8]]);
  });

  it("has nothing to compare with in January", () => {
    const { result } = sampleKpi(year, 0);
    expect(result.rows).toEqual([[byMonth[0], null, null]]);
  });
});
