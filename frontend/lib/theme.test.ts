import { describe, expect, it } from "vitest";
import catalogueJson from "@/lib/__fixtures__/catalogue.json";
import { CATEGORY_COLORS, darkStep, OTHERS_COLOR } from "@/lib/colors";
import { defaultConfig, normalizeConfig } from "@/lib/insights";
import type { Catalogue, PanelConfig, QueryResult } from "@/lib/types";
import { toOption } from "@/components/charts/toOption";
import { CHART_LOOKS, isThemeChoice, resolveTheme, THEME_OPTIONS } from "./theme";

const catalogue = catalogueJson as unknown as Catalogue;

describe("resolveTheme", () => {
  it("keeps an explicit mode", () => {
    expect(resolveTheme("classic", true)).toBe("classic");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("turns Match device into Light or Dark", () => {
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("system", true)).toBe("dark");
  });
});

describe("isThemeChoice", () => {
  it("accepts only the known ids (the server's THEME_CHOICES)", () => {
    expect(THEME_OPTIONS.map((t) => t.id)).toEqual(["classic", "light", "dark", "system"]);
    expect(THEME_OPTIONS.every((t) => isThemeChoice(t.id))).toBe(true);
    for (const bad of ["white", "DARK", "", null, 1, undefined]) expect(isThemeChoice(bad)).toBe(false);
  });
});

describe("darkStep", () => {
  it("gives every default colour, and Others, its own dark step", () => {
    const steps = [...CATEGORY_COLORS, OTHERS_COLOR].map(darkStep);
    expect(steps.every((c) => /^#[0-9A-F]{6}$/.test(c))).toBe(true);
    expect(new Set(steps).size).toBe(steps.length); // still all distinct
    expect(darkStep("#2a78d6")).toBe("#3987E5"); // case doesn't matter
  });

  it("leaves a colour the user picked alone", () => {
    expect(darkStep("#123456")).toBe("#123456");
  });
});

describe("charts in each mode", () => {
  const config = normalizeConfig({ ...defaultConfig("bar"), x: { field: "category" } }, catalogue) as PanelConfig;
  const data: QueryResult = {
    columns: ["x", "value"],
    rows: [["Food", "10"], ["Rent", "20"]],
    meta: { chart: "bar" },
    period: { from: "2026-01-01", to: "2026-03-31" },
  };
  /* eslint-disable @typescript-eslint/no-explicit-any */
  const bars = (theme: keyof typeof CHART_LOOKS): any[] =>
    (toOption(config, data, new Map(), undefined, CHART_LOOKS[theme]).option as any).series[0].data;

  it("outline bars in ink in Classic, the default", () => {
    const classic = (toOption(config, data).option as any).series[0].data;
    expect(classic[0].itemStyle).toMatchObject({ color: CATEGORY_COLORS[0], borderColor: "#111111" });
    expect(bars("classic")).toEqual(classic);
  });

  it("separate bars with a surface gap, and use the dark steps, in Dark", () => {
    const [first, second] = bars("dark");
    expect(first.itemStyle).toMatchObject({ color: darkStep(CATEGORY_COLORS[0]), borderColor: CHART_LOOKS.dark.surface });
    expect(second.itemStyle.color).toBe(darkStep(CATEGORY_COLORS[1]));
  });

  it("draw a heatmap's scale from the mode's own ramp", () => {
    const calendar = normalizeConfig(defaultConfig("calendar"), catalogue) as PanelConfig;
    const days: QueryResult = { ...data, columns: ["x", "value"], rows: [["2026-01-01", "5"]] };
    const option = toOption(calendar, days, new Map(), undefined, CHART_LOOKS.dark).option as any;
    expect(option.visualMap.inRange.color).toEqual(CHART_LOOKS.dark.sequential);
    expect(option.calendar.itemStyle.color).toBe(CHART_LOOKS.dark.emptyCell);
  });
});
