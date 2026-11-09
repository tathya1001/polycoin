import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { darkStep } from "@/lib/colors";
import { SAMPLE_GROUPS } from "@/lib/sampleYear";

// A series colour for a mark drawn outside the chart library: the colour and its dark step, as
// CSS variables. The `series-mark` class (globals.css) picks the one for the colour mode.
export function markStyle(color: string): CSSProperties {
  return { "--mark-light": color, "--mark-dark": darkStep(color) } as CSSProperties;
}

// One panel of the dashboard preview: a dashboard panel's title bar and body, without its edit
// menu. It rises into place once, `delay` ms after the page appears.
export function PreviewPanel({
  title,
  delay,
  className,
  children,
}: {
  title: string;
  delay: number;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn("preview-rise flex min-w-0 flex-col overflow-hidden rounded-md border-[1.5px] border-hairline", className)}
      style={{ animationDelay: `${delay}ms` }}
    >
      <p className="truncate border-b border-hairline px-3 py-2 text-sm font-semibold">{title}</p>
      <div className="min-h-0 flex-1 p-3">{children}</div>
    </div>
  );
}

// The series names with their colours.
export function PreviewLegend({ className }: { className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2", className)}>
      {SAMPLE_GROUPS.map((group) => (
        <li key={group.name} className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="series-mark size-2.5 shrink-0 rounded-[3px] bg-(--mark)" style={markStyle(group.color)} />
          {group.name}
        </li>
      ))}
    </ul>
  );
}
