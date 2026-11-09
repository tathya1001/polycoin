import KpiPanel from "@/components/charts/KpiPanel";
import { groupMonthTotals, groupTotals, sampleKpi, sampleYear } from "@/lib/sampleYear";
import { AreaPreview } from "./AreaPreview";
import { DonutPreview } from "./DonutPreview";
import { PreviewLegend, PreviewPanel } from "./PreviewParts";

const YEAR = sampleYear();
const KPI_MONTH = 8; // September (0 = January)

// The home page's picture of the product: three panels of a dashboard, filled from a made-up
// year. The Number panel is the app's own; the stacked area and the donut are plain SVG drawn
// like the app's charts, so the page loads no chart library. Purely a picture: hidden from
// screen readers (the headline says what it shows) and not interactive.
//
// Widths: phones show the Number panel and the stacked area; from md the donut joins beside the
// Number panel with the area under both; from lg all three share one row.
export function DashboardPreview() {
  const kpi = sampleKpi(YEAR, KPI_MONTH);
  return (
    <div aria-hidden className="rounded-lg border-[1.5px] border-line bg-canvas p-2 shadow-pop sm:p-3">
      <div className="grid gap-2 sm:gap-3 md:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1.3fr)]">
        {/* A fixed height on phones: the trend line fills its panel, and the panel has no row
            neighbour there to take its height from. */}
        <PreviewPanel title="Spent in September" delay={0} className="max-md:h-60">
          <KpiPanel config={kpi.config} result={kpi.result} />
        </PreviewPanel>
        <PreviewPanel
          title="Spend by month"
          delay={120}
          className="md:col-span-2 md:row-start-2 lg:col-span-1 lg:row-start-auto"
        >
          <div className="flex h-full flex-col gap-3">
            <div className="min-h-48 flex-1">
              <AreaPreview byGroup={groupMonthTotals(YEAR)} />
            </div>
            <PreviewLegend />
          </div>
        </PreviewPanel>
        <PreviewPanel title="Where it went" delay={240} className="max-md:hidden">
          <div className="flex h-full items-center justify-center gap-4">
            <DonutPreview totals={groupTotals(YEAR)} />
            <PreviewLegend className="flex-col flex-nowrap" />
          </div>
        </PreviewPanel>
      </div>
    </div>
  );
}
