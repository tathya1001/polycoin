import type { ComponentProps, ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

export function Card({
  padded = true,
  interactive = false,
  className,
  ...rest
}: ComponentProps<"div"> & { padded?: boolean; interactive?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-md border-[1.5px] border-line bg-surface shadow-card",
        padded && "p-5",
        interactive && "transition-[transform,box-shadow] duration-150 hover:-translate-y-px hover:shadow-hard",
        className,
      )}
      {...rest}
    />
  );
}

type ChipProps = {
  active?: boolean;
  onClick?: () => void;
  onRemove?: () => void;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
};

// A pill: a filter, a keyword, a choice. Becomes a button when it can be clicked.
export function Chip({ active, onClick, onRemove, icon, className, children }: ChipProps) {
  const look = cn(
    "inline-flex h-8 items-center gap-1.5 rounded-full border-[1.5px] border-edge px-3 text-[13px] font-medium whitespace-nowrap transition-colors duration-150",
    active ? "bg-fill text-on-fill" : "bg-surface text-ink",
    onClick && !active && "hover:bg-wash",
    className,
  );
  const body = (
    <>
      {icon}
      {children}
    </>
  );
  if (!onRemove) {
    return onClick ? (
      <button type="button" onClick={onClick} aria-pressed={active} className={look}>
        {body}
      </button>
    ) : (
      <span className={look}>{body}</span>
    );
  }
  return (
    <span className={cn(look, "pr-1.5")}>
      {body}
      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove"
        className="grid size-5 place-items-center rounded-full hover:bg-ink/10"
      >
        <X size={13} aria-hidden />
      </button>
    </span>
  );
}

export type BadgeTone = "neutral" | "pos" | "neg" | "warn" | "ink";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-wash text-ink-2",
  pos: "bg-pos-bg text-pos",
  neg: "bg-neg-bg text-neg",
  warn: "bg-warn-bg text-warn-ink",
  ink: "bg-fill text-on-fill",
};

export function Badge({ tone = "neutral", className, ...rest }: ComponentProps<"span"> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone], className)}
      {...rest}
    />
  );
}
