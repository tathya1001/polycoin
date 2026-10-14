// Every font the user can pick in Settings > Appearance. This list is the single source for the
// Settings page, the saved-preference check and the TypeScript type. Three other places must stay
// in step with it (add a font in all four):
//   1. app/fonts.ts                     the next/font import (loads and self-hosts the font)
//   2. app/globals.css                  an html[data-font="<id>"] rule
//   3. backend/accounts/models.py       UserPreferences.FONT_CHOICES (+ a migration)

export type FontKind = "sans" | "serif" | "mono";

export const FONT_OPTIONS = [
  { id: "geist", name: "Geist", kind: "sans", cssVar: "--font-geist-sans" },
  { id: "inter", name: "Inter", kind: "sans", cssVar: "--font-inter" },
  { id: "space-grotesk", name: "Space Grotesk", kind: "sans", cssVar: "--font-space-grotesk" },
  { id: "plex-sans", name: "IBM Plex Sans", kind: "sans", cssVar: "--font-plex-sans" },
  { id: "geologica", name: "Geologica", kind: "sans", cssVar: "--font-geologica" },
  { id: "source-serif", name: "Source Serif 4", kind: "serif", cssVar: "--font-source-serif" },
  { id: "instrument-serif", name: "Instrument Serif", kind: "serif", cssVar: "--font-instrument-serif" },
  { id: "bitter", name: "Bitter", kind: "serif", cssVar: "--font-bitter" },
  { id: "crimson-pro", name: "Crimson Pro", kind: "serif", cssVar: "--font-crimson-pro" },
  { id: "spectral", name: "Spectral", kind: "serif", cssVar: "--font-spectral" },
  { id: "plex-mono", name: "IBM Plex Mono", kind: "mono", cssVar: "--font-plex-mono" },
  { id: "xanh-mono", name: "Xanh Mono", kind: "mono", cssVar: "--font-xanh-mono" },
  { id: "vt323", name: "VT323", kind: "mono", cssVar: "--font-vt323" },
] as const satisfies readonly { id: string; name: string; kind: FontKind; cssVar: string }[];

export type FontChoice = (typeof FONT_OPTIONS)[number]["id"];

export const DEFAULT_FONT: FontChoice = "geist";

const IDS: readonly string[] = FONT_OPTIONS.map((font) => font.id);

export function isFontChoice(value: unknown): value is FontChoice {
  return typeof value === "string" && IDS.includes(value);
}

// Fonts whose letters globals.css enlarges with font-size-adjust. Charts draw their own text
// (ECharts measures it itself and ignores that CSS), so they enlarge their text by the same
// factor. Keep in step with the font-size-adjust rules in globals.css.
export const CHART_TEXT_SCALE: Partial<Record<FontChoice, number>> = {
  vt323: 1.3,
  "crimson-pro": 1.19,
  spectral: 1.1,
  "instrument-serif": 1.12,
};

// What to fall back to while a font is loading, or if it fails to load.
export const FALLBACKS: Record<FontKind, string> = {
  sans: "system-ui, sans-serif",
  serif: 'Georgia, "Times New Roman", serif',
  mono: 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace',
};

// A CSS font-family value for previews: the loaded font, then its fallback.
export function fontFamilyOf(font: (typeof FONT_OPTIONS)[number]): string {
  return `var(${font.cssVar}), ${FALLBACKS[font.kind]}`;
}
