// Colours for charts. Every category owns one (its default in all charts); a panel can
// override any series. Keep CATEGORY_COLORS in step with backend/categories/colors.py.

// Slots 1-8 are the dataviz skill's reference palette, validated for colour-blind separation
// on a white surface (fixed order, never cycled). Slots 9-12 sit outside that validated set:
// they only exist so a 9th-12th category gets a distinct default. Charts therefore always
// pair colour with a legend and tooltips, never colour alone.
export const CATEGORY_COLORS = [
  "#2A78D6", // blue
  "#EB6834", // orange
  "#1BAF7A", // aqua
  "#EDA100", // yellow
  "#E87BA4", // magenta
  "#008300", // green
  "#6250D6", // violet
  "#E34948", // red
  "#0E9FB5", // cyan
  "#8D6E63", // brown
  "#84A912", // olive
  "#5B6B7F", // slate
] as const;

export const OTHERS_COLOR = "#9CA3AF";

// Used for series that have no category colour and no override: position decides.
export const FALLBACK_SERIES_COLORS = CATEGORY_COLORS;

export const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/;

export function isHexColor(value: string): boolean {
  return HEX_COLOR.test(value);
}

export function normalizeHex(value: string): string {
  return value.trim().toUpperCase();
}

// Black or white text, whichever reads better on `background`.
export function readableOn(background: string): "#111111" | "#ffffff" {
  if (!isHexColor(background)) return "#111111";
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(background.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#111111" : "#ffffff";
}
