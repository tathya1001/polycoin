import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

// A row of numbered steps. `current` is the 0-based index of the active one.
export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-2">
      {steps.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} className="flex items-center gap-2" aria-current={active ? "step" : undefined}>
            <span
              className={cn(
                "grid size-7 place-items-center rounded-full border-[1.5px] border-edge text-xs font-semibold transition-colors",
                done && "bg-fill text-on-fill",
                active && "bg-surface shadow-hard-sm",
                !done && !active && "border-ink/30 text-muted",
              )}
            >
              {done ? <Check size={14} strokeWidth={3} aria-hidden /> : index + 1}
            </span>
            <span className={cn("text-sm font-medium", !done && !active && "text-muted")}>{label}</span>
            {index < steps.length - 1 && <span aria-hidden className="mx-1 h-px w-8 bg-ink/30" />}
          </li>
        );
      })}
    </ol>
  );
}
