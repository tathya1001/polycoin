// Colour modes (Settings > Appearance). The page's colours are CSS tokens in app/globals.css,
// switched by data-theme on <html>: no attribute is Classic, "light" and "dark" are the soft
// modes. "Match device" is not a look of its own: it resolves to Light or Dark from the
// device's setting. Keep THEME_OPTIONS in step with backend/accounts/models.py THEME_CHOICES.

import { darkStep } from "@/lib/colors";

export const THEME_OPTIONS = [
  { id: "classic", name: "Classic", blurb: "Bold black outlines and hard shadows. The original look." },
  { id: "light", name: "Light", blurb: "A clean white tone, softer than pure white." },
  { id: "dark", name: "Dark", blurb: "Neutral black with soft text, easy on the eyes at night." },
  { id: "system", name: "Match device", blurb: "Light or Dark, following your device's setting." },
] as const;

export type ThemeChoice = (typeof THEME_OPTIONS)[number]["id"];
export type ResolvedTheme = "classic" | "light" | "dark";

export const DEFAULT_THEME: ThemeChoice = "classic";
export const DARK_QUERY = "(prefers-color-scheme: dark)";

const IDS: readonly string[] = THEME_OPTIONS.map((theme) => theme.id);

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return typeof value === "string" && IDS.includes(value);
}

export function resolveTheme(choice: ThemeChoice, prefersDark: boolean): ResolvedTheme {
  if (choice === "system") return prefersDark ? "dark" : "light";
  return choice;
}

export function applyTheme(theme: ResolvedTheme) {
  if (theme === "classic") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}

// --- charts ------------------------------------------------------------------------------------
// ECharts draws on its own and can't read CSS variables, so the colours it needs are mirrored
// here. Keep the chrome values in step with the tokens in app/globals.css.

export type ChartLook = {
  text: string; // ink
  muted: string; // ink-2: axis labels, legend
  axis: string; // the category axis line
  grid: string; // value grid lines
  surface: string; // the panel behind the chart
  band: string; // alternate rows/columns of a matrix heatmap, axis-pointer shade
  // The edge around a bar or slice. Classic outlines marks in ink; the soft modes separate
  // neighbouring marks with a thin gap the colour of the surface instead.
  barEdge: { color: string; width: number };
  sliceEdge: { color: string; width: number };
  calendarLine: string; // the month borders of a calendar heatmap
  emptyCell: string; // a calendar day with no data
  tooltip: { background: string; border: string };
  pager: { active: string; inactive: string }; // the arrows of a legend too long to fit
  sequential: string[]; // small -> large, one hue
  diverging: string[]; // below zero -> neutral -> above zero
  series: (color: string) => string; // a series colour as this mode draws it
};

const same = (color: string) => color;

export const CHART_LOOKS: Record<ResolvedTheme, ChartLook> = {
  // `surface` is what the chart draws on: the page colour, since dashboard panels have no fill
  // of their own. Gaps between marks and the rings around points use it.
  classic: {
    text: "#111111",
    muted: "#4a4a4a",
    axis: "#111111",
    grid: "#e4e2dc",
    surface: "#f7f6f2",
    band: "rgba(17,17,17,0.04)",
    barEdge: { color: "#111111", width: 1 },
    sliceEdge: { color: "#111111", width: 1.5 },
    calendarLine: "#111111",
    emptyCell: "#ebe9e2",
    tooltip: { background: "#ffffff", border: "#111111" },
    pager: { active: "#2f4554", inactive: "#aaaaaa" }, // the ECharts defaults
    sequential: ["#EAF2FC", "#2A78D6", "#12407A"],
    diverging: ["#EB6834", "#F7F5F0", "#2A78D6"],
    series: same,
  },
  light: {
    text: "#2b2b2e",
    muted: "#56565c",
    axis: "#cfceca",
    grid: "#eeede9",
    surface: "#fbfbf9",
    band: "rgba(43,43,46,0.04)",
    barEdge: { color: "#fbfbf9", width: 1 },
    sliceEdge: { color: "#fbfbf9", width: 2 },
    calendarLine: "#d9d8d3",
    emptyCell: "#f1f0ec",
    tooltip: { background: "#fefefd", border: "#e4e3df" },
    pager: { active: "#56565c", inactive: "#d2d1cc" },
    sequential: ["#EAF2FC", "#2A78D6", "#12407A"],
    diverging: ["#EB6834", "#EFEEEA", "#2A78D6"],
    series: same,
  },
  dark: {
    text: "#d6d6d8",
    muted: "#a8a8ad",
    axis: "#38383c",
    grid: "#222224",
    surface: "#0f0f10",
    band: "rgba(214,214,216,0.04)",
    barEdge: { color: "#0f0f10", width: 1 },
    sliceEdge: { color: "#0f0f10", width: 2 },
    calendarLine: "#38383c",
    emptyCell: "#1c1c1f",
    tooltip: { background: "#1e1e21", border: "#2c2c2f" },
    pager: { active: "#a8a8ad", inactive: "#38383c" },
    // On dark, "near zero" recedes into the black and large values glow.
    sequential: ["#18202E", "#3987E5", "#B7D3F6"],
    diverging: ["#D95926", "#303034", "#3987E5"],
    series: darkStep,
  },
};
