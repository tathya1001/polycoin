import { cn } from "@/lib/cn";

// Two overlapping coins: "poly" + "coin". Pure SVG, inherits colour from the text.
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden className={cn("shrink-0", className)}>
      <circle cx="12" cy="16" r="9" fill="currentColor" />
      <circle cx="20" cy="16" r="9" stroke="currentColor" strokeWidth="2" />
      <circle cx="12" cy="16" r="3" className="fill-surface" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return <span className={cn("text-lg font-semibold tracking-tight", className)}>Polycoin</span>;
}
