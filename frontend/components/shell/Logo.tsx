import { cn } from "@/lib/cn";

// The name, set in type. There is no logo mark for now: the owner will supply one, and it goes
// next to this (sidebar, mobile header, sign-in pages, landing page).
export function Wordmark({ className }: { className?: string }) {
  return <span className={cn("text-lg font-semibold tracking-tight", className)}>MoneyAngle</span>;
}
