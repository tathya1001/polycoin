"use client";

// The one place ECharts touches the DOM. Loaded with next/dynamic (ssr: false) by PanelBody,
// because ECharts needs `window` and a real element to draw on.

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";
import { CATEGORY_COLORS } from "@/lib/colors";
import { CHART_TEXT_SCALE } from "@/lib/fonts";
import { useSession } from "@/components/shell/Session";
import type { ChartOption } from "./toOption";

// Tree-shaken: only the chart types and components the dashboard uses are bundled.
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
  CanvasRenderer,
]);

// The Polycoin look: ink text and axes, hairline dashed grid lines, a tooltip that is a
// small brutalist card. Series colours are set per series in toOption; `color` is only the
// fallback ECharts uses for anything we did not colour.
const INK = "#111111";
const MUTED = "#4a4a4a";
const HAIRLINE = "#e4e2dc";

function themeFor(fontFamily: string, scale: number) {
  const size = (px: number) => Math.round(px * scale * 10) / 10;
  const axisLabel = { color: MUTED, fontSize: size(12) };
  return {
    color: [...CATEGORY_COLORS],
    backgroundColor: "transparent",
    textStyle: { fontFamily, color: INK, fontSize: size(12) },
    categoryAxis: {
      axisLine: { show: true, lineStyle: { color: INK, width: 1.5 } },
      axisTick: { show: false },
      axisLabel,
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel,
      splitLine: { show: true, lineStyle: { color: HAIRLINE, type: "dashed" as const } },
    },
    legend: {
      icon: "roundRect",
      itemWidth: 12,
      itemHeight: 12,
      itemGap: 14,
      textStyle: { color: MUTED, fontSize: size(12) },
    },
    tooltip: {
      backgroundColor: "#ffffff",
      borderColor: INK,
      borderWidth: 1.5,
      padding: [8, 12],
      textStyle: { color: INK, fontSize: size(13) },
      extraCssText: "border-radius:12px;box-shadow:3px 3px 0 #111111;",
      axisPointer: {
        lineStyle: { color: INK, width: 1 },
        shadowStyle: { color: "rgba(17,17,17,0.06)" },
      },
    },
  };
}

type Props = {
  option: ChartOption;
  // A click on a bar / point / slice, by series and data index (see ChartKeys in toOption).
  onPick?: (seriesIndex: number, dataIndex: number) => void;
};

export default function EChart({ option, onPick }: Props) {
  // Settings > Charts: "quality" draws SVG (vector, sharp at any zoom), "performance" draws a
  // pixel canvas (faster when a chart has thousands of points).
  const { preferences } = useSession();
  const renderer = preferences.chart_quality === "performance" ? "canvas" : "svg";
  const font = preferences.font;
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const latestOption = useRef(option);
  const latestPick = useRef(onPick);

  // Refs are only written in effects (never during render), as React 19 requires.
  useEffect(() => {
    latestOption.current = option;
    latestPick.current = onPick;
  });

  // Create the chart (again whenever the renderer or the font changes), keep it sized to its box (panels
  // are resized by dragging), and dispose of it when the panel goes away.
  useEffect(() => {
    const node = element.current;
    if (!node) return;

    // ECharts cannot read CSS variables: hand it the page's current font (Geist or Inter,
    // whichever the user picked in Settings) as a plain string.
    const fontFamily = getComputedStyle(document.body).fontFamily;
    const scale = CHART_TEXT_SCALE[font] ?? 1;
    const themeName = `polycoin-${fontFamily}-${scale}`;
    echarts.registerTheme(themeName, themeFor(fontFamily, scale));

    const instance = echarts.init(node, themeName, { renderer });
    instance.setOption(latestOption.current);
    instance.on("click", (params) => {
      latestPick.current?.(params.seriesIndex ?? 0, params.dataIndex);
    });
    chart.current = instance;

    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(node);
    return () => {
      resize.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [renderer, font]); // switching the renderer or the font in Settings re-creates the chart

  // New data or new settings: replace the whole option, so nothing from the old one lingers.
  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  // font-size-adjust: none, because ECharts lays text out by itself (see CHART_TEXT_SCALE).
  return <div ref={element} className="h-full w-full [font-size-adjust:none]" />;
}
