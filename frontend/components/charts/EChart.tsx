"use client";

// The one place ECharts touches the DOM. Loaded with next/dynamic (ssr: false) by PanelBody,
// because ECharts needs `window` and a real element to draw on.

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import { CalendarComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";
import { CATEGORY_COLORS } from "@/lib/colors";
import { CHART_TEXT_SCALE } from "@/lib/fonts";
import { CHART_LOOKS, type ChartLook } from "@/lib/theme";
import { useSession } from "@/components/shell/Session";
import type { ChartOption } from "./toOption";

// Tree-shaken: only the chart types and components the dashboard uses are bundled.
echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  PieChart,
  CalendarComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  SVGRenderer,
  CanvasRenderer,
]);

// The chart chrome comes from the colour mode (lib/theme.ts CHART_LOOKS): text, axes, a recessive
// dashed grid, and a tooltip that is a small flat card (dashboards carry no shadows). Series
// colours are set per series in toOption; `color` is only the fallback ECharts uses for
// anything we did not colour.
function themeFor(fontFamily: string, scale: number, look: ChartLook) {
  const size = (px: number) => Math.round(px * scale * 10) / 10;
  const axisLabel = { color: look.muted, fontSize: size(12) };
  return {
    color: CATEGORY_COLORS.map(look.series),
    backgroundColor: "transparent",
    textStyle: { fontFamily, color: look.text, fontSize: size(12) },
    categoryAxis: {
      axisLine: { show: true, lineStyle: { color: look.axis, width: 1.5 } },
      axisTick: { show: false },
      axisLabel,
      splitLine: { show: false },
      splitArea: { areaStyle: { color: ["transparent", look.band] } },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel,
      splitLine: { show: true, lineStyle: { color: look.grid, type: "dashed" as const } },
    },
    legend: {
      icon: "roundRect",
      itemWidth: 12,
      itemHeight: 12,
      itemGap: 14,
      textStyle: { color: look.muted, fontSize: size(12) },
      pageIconColor: look.pager.active,
      pageIconInactiveColor: look.pager.inactive,
      pageTextStyle: { color: look.muted },
    },
    visualMap: { textStyle: { color: look.muted, fontSize: size(12) } },
    calendar: {
      dayLabel: { color: look.muted },
      monthLabel: { color: look.muted },
    },
    tooltip: {
      backgroundColor: look.tooltip.background,
      borderColor: look.tooltip.border,
      borderWidth: 1.5,
      padding: [8, 12],
      textStyle: { color: look.text, fontSize: size(13) },
      extraCssText: "border-radius:12px;box-shadow:none;",
      axisPointer: {
        lineStyle: { color: look.muted, width: 1 },
        shadowStyle: { color: look.band },
      },
    },
  };
}

type Props = {
  option: ChartOption;
  // A click on a bar / point / slice, by series and data index (see ChartKeys in toOption),
  // and where in the chart it happened, in pixels from its top-left corner.
  onPick?: (seriesIndex: number, dataIndex: number, at: { x: number; y: number }) => void;
};

export default function EChart({ option, onPick }: Props) {
  // Settings > Charts: "quality" draws SVG (vector, sharp at any zoom), "performance" draws a
  // pixel canvas (faster when a chart has thousands of points).
  const { preferences, theme } = useSession();
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

  // Create the chart (again whenever the renderer, the font or the colour mode changes), keep it sized to its box (panels
  // are resized by dragging), and dispose of it when the panel goes away.
  useEffect(() => {
    const node = element.current;
    if (!node) return;

    // ECharts cannot read CSS variables: hand it the page's current font (Geist or Inter,
    // whichever the user picked in Settings) as a plain string.
    const fontFamily = getComputedStyle(document.body).fontFamily;
    const scale = CHART_TEXT_SCALE[font] ?? 1;
    const themeName = `polycoin-${theme}-${fontFamily}-${scale}`;
    echarts.registerTheme(themeName, themeFor(fontFamily, scale, CHART_LOOKS[theme]));

    const instance = echarts.init(node, themeName, { renderer });
    instance.setOption(latestOption.current);
    instance.on("click", (params) => {
      // zrender gives the position relative to the chart, whichever renderer draws it
      latestPick.current?.(params.seriesIndex ?? 0, params.dataIndex, {
        x: params.event?.offsetX ?? 0,
        y: params.event?.offsetY ?? 0,
      });
    });
    chart.current = instance;

    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(node);
    return () => {
      resize.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [renderer, font, theme]); // switching the renderer, font or colour mode re-creates the chart

  // New data or new settings: replace the whole option, so nothing from the old one lingers.
  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  // font-size-adjust: none, because ECharts lays text out by itself (see CHART_TEXT_SCALE).
  return <div ref={element} className="h-full w-full [font-size-adjust:none]" />;
}
