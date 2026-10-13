"use client";

// The one place ECharts touches the DOM. Loaded with next/dynamic (ssr: false) by PanelBody,
// because ECharts needs `window` and a real element to draw on.

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ChartOption } from "./toOption";

// Tree-shaken: only the chart types and components the dashboard uses are bundled.
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type Props = {
  option: ChartOption;
  // A click on a bar / point / slice, by series and data index (see ChartKeys in toOption).
  onPick?: (seriesIndex: number, dataIndex: number) => void;
};

export default function EChart({ option, onPick }: Props) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const latestOption = useRef(option);
  const latestPick = useRef(onPick);

  // Refs are only written in effects (never during render), as React 19 requires.
  useEffect(() => {
    latestOption.current = option;
    latestPick.current = onPick;
  });

  // Create the chart once, re-create it when the OS switches light / dark, keep it sized to
  // its box (panels are resized by dragging), and dispose of it when the panel goes away.
  useEffect(() => {
    const node = element.current;
    if (!node) return;
    const dark = window.matchMedia("(prefers-color-scheme: dark)");

    function create() {
      chart.current?.dispose();
      const instance = echarts.init(node, dark.matches ? "dark" : undefined);
      instance.setOption({ ...latestOption.current, backgroundColor: "transparent" });
      instance.on("click", (params) => {
        latestPick.current?.(params.seriesIndex ?? 0, params.dataIndex);
      });
      chart.current = instance;
    }

    create();
    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(node);
    dark.addEventListener("change", create);
    return () => {
      dark.removeEventListener("change", create);
      resize.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  // New data or new settings: replace the whole option, so nothing from the old one lingers.
  useEffect(() => {
    chart.current?.setOption({ ...option, backgroundColor: "transparent" }, { notMerge: true });
  }, [option]);

  return <div ref={element} className="h-full w-full" />;
}
