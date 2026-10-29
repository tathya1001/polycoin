import type { ComponentProps, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export function Spinner({ size = 18, className }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={cn("animate-spin text-ink-2", className)} aria-hidden />;
}

// "Loading…" with the ellipsis character, everywhere.
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="flex items-center gap-2 py-8 text-ink-2">
      <Spinner />
      {label}
    </p>
  );
}

export function Skeleton({ className, ...rest }: ComponentProps<"div">) {
  return <div aria-hidden className={cn("animate-[skeleton_1.4s_ease-in-out_infinite] rounded-sm bg-hairline", className)} {...rest} />;
}

export function EmptyState({
  icon,
  title,
  children,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-md border-[1.5px] border-dashed border-ink/40 bg-surface/60 px-6 py-12 text-center",
        className,
      )}
    >
      {icon && <div className="grid size-12 place-items-center rounded-full border-[1.5px] border-line bg-surface">{icon}</div>}
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {children && <p className="max-w-md text-ink-2">{children}</p>}
      {action}
    </div>
  );
}

// An inline problem, in place (not a toast): a failed load, a bad file.
export function ErrorNote({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      role="alert"
      className={cn("rounded-sm border-[1.5px] border-neg bg-neg-wash px-3 py-2 text-sm font-medium text-neg", className)}
    >
      {children}
    </p>
  );
}
