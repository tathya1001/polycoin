// A made-up year of spending for the dashboard preview on the home page. A fixed seed gives the
// same year on every build, so the page is rendered once on the server and served as static HTML.
// Amounts are whole rupees. Nothing here is a real person's data.

import { CATEGORY_COLORS, OTHERS_COLOR } from "@/lib/colors";
import { defaultConfig, defaultKpi } from "@/lib/insights";
import type { PanelConfig, QueryResult } from "@/lib/types";

export const SAMPLE_YEAR = 2025;
const SAMPLE_SEED = 2025;

// The preview's series, in stacking order (the first is at the bottom of the stacked area).
export const SAMPLE_GROUPS = [
  { name: "Rent", color: CATEGORY_COLORS[6] },
  { name: "Food & dining", color: CATEGORY_COLORS[1] },
  { name: "Groceries", color: CATEGORY_COLORS[2] },
  { name: "Shopping", color: CATEGORY_COLORS[4] },
  { name: "Travel", color: CATEGORY_COLORS[0] },
  { name: "Others", color: OTHERS_COLOR },
] as const;

const RENT = 0;
const FOOD = 1;
const GROCERIES = 2;
const SHOPPING = 3;
const TRAVEL = 4;
const OTHERS = 5;

// One day: its date ("2025-03-14") and what was spent in each of SAMPLE_GROUPS, by position.
export type SampleDay = { date: string; amounts: number[] };

const DAY_MS = 86_400_000;

// mulberry32: a small seeded generator with a good spread. For made-up numbers only, never for
// anything secret.
function seeded(seed: number): () => number {
  let state = seed | 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Every day of `year`, with a pattern a real statement has: rent on the 1st, bills early in the
// month, busier weekends, two week-long trips and a festival season from mid-October.
export function sampleYear(year = SAMPLE_YEAR, seed = SAMPLE_SEED): SampleDay[] {
  const random = seeded(seed);
  const between = (low: number, high: number) => low + random() * (high - low);
  const start = Date.UTC(year, 0, 1);
  const count = Math.round((Date.UTC(year + 1, 0, 1) - start) / DAY_MS);

  const days: SampleDay[] = [];
  for (let index = 0; index < count; index++) {
    const date = new Date(start + index * DAY_MS);
    const day = date.getUTCDate();
    const month = date.getUTCMonth();
    const weekday = date.getUTCDay();
    const weekend = weekday === 0 || weekday === 6;
    const festive = (month === 9 && day >= 12) || (month === 10 && day <= 12);
    const trip = (month === 4 && day >= 9 && day <= 15) || (month === 11 && day >= 22 && day <= 28);

    const amounts: number[] = SAMPLE_GROUPS.map(() => 0);
    if (day === 1) amounts[RENT] += 18_000;
    if (day >= 5 && day <= 7 && random() < 0.6) amounts[OTHERS] += between(900, 3100); // bills
    if (random() < (weekend ? 0.5 : 0.3)) amounts[GROCERIES] += between(300, 1800);
    const meals = weekend ? 2 : random() < 0.6 ? 1 : 0;
    for (let meal = 0; meal < meals; meal++) amounts[FOOD] += between(150, weekend ? 1550 : 750);
    if (random() < (festive ? 0.85 : 0.12)) amounts[SHOPPING] += festive ? between(1200, 4700) : between(400, 2900);
    if (trip) amounts[TRAVEL] += between(2000, 6000);
    else if (!weekend && random() < 0.5) amounts[TRAVEL] += between(60, 240); // the commute
    if (random() < 0.03) amounts[OTHERS] += between(500, 5500); // health
    if (random() < (weekend ? 0.35 : 0.08)) amounts[OTHERS] += between(300, 1900); // going out

    days.push({ date: date.toISOString().slice(0, 10), amounts: amounts.map(Math.round) });
  }
  return days;
}

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
const monthOf = (day: SampleDay) => Number(day.date.slice(5, 7)) - 1;

// Spend per group and month: totals[group][month].
export function groupMonthTotals(days: SampleDay[]): number[][] {
  const totals = SAMPLE_GROUPS.map(() => Array<number>(12).fill(0));
  for (const day of days) day.amounts.forEach((amount, group) => (totals[group][monthOf(day)] += amount));
  return totals;
}

// Spend per month, all groups together.
export function monthTotals(days: SampleDay[]): number[] {
  const byGroup = groupMonthTotals(days);
  return byGroup[0].map((_, month) => sum(byGroup.map((group) => group[month])));
}

// Spend per group over the whole year.
export function groupTotals(days: SampleDay[]): number[] {
  return groupMonthTotals(days).map(sum);
}

// The change from `previous` to `current` in percent, to one decimal, as the server sends a KPI's
// change. Null when there is nothing to compare with.
export function percentChange(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) / previous) * 1000) / 10;
}

// The grid lines of a value axis that starts at 0: about `count` round steps (1, 2, 2.5 or 5 times
// a power of ten), the last one at or above `max`.
export function axisTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0];
  const raw = max / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * power).find((candidate) => candidate >= raw) ?? raw;
  const steps = Math.ceil(max / step);
  return Array.from({ length: steps + 1 }, (_, index) => index * step);
}

const pad = (value: number) => String(value).padStart(2, "0");

// A Number panel for one month (0 = January): its spend against the month before, and the trend
// from January. Shaped like the server's answer for a KPI panel, so the app's own panel draws it.
export function sampleKpi(days: SampleDay[], month: number): { config: PanelConfig; result: QueryResult } {
  const year = Number(days[0].date.slice(0, 4));
  const totals = monthTotals(days);
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return {
    config: { ...defaultConfig("kpi"), kpi: { ...defaultKpi(), compare: "previous", sparkline: "month" } },
    result: {
      columns: ["value", "previous", "change_pct"],
      rows: [[totals[month], totals[month - 1] ?? null, month > 0 ? percentChange(totals[month], totals[month - 1]) : null]],
      meta: { chart: "kpi" },
      period: { from: `${year}-${pad(month + 1)}-01`, to: `${year}-${pad(month + 1)}-${pad(lastDay)}` },
      sparkline: {
        granularity: "month",
        columns: ["x", "value"],
        rows: totals.slice(0, month + 1).map((total, index) => [`${year}-${pad(index + 1)}-01`, total]),
      },
    },
  };
}
