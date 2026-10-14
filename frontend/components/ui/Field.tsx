import type { ComponentProps, ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

const CONTROL =
  "w-full border-[1.5px] border-ink bg-surface text-ink placeholder:text-muted " +
  "transition-shadow duration-150 focus-visible:shadow-hard-sm " +
  "aria-[invalid=true]:border-neg disabled:cursor-not-allowed disabled:bg-wash disabled:text-muted";

type Dense = { dense?: boolean };

export function Input({ dense, className, ...rest }: ComponentProps<"input"> & Dense) {
  return (
    <input
      className={cn(CONTROL, dense ? "h-8 rounded-sm px-2.5 text-[13px]" : "h-10 rounded-sm px-3 text-sm", className)}
      {...rest}
    />
  );
}

export function Textarea({ className, ...rest }: ComponentProps<"textarea">) {
  return <textarea className={cn(CONTROL, "min-h-20 rounded-sm px-3 py-2 text-sm", className)} {...rest} />;
}

// className goes on the wrapper (so `w-48` or `flex-1` sizes the whole control).
export function Select({
  dense,
  className,
  children,
  ...rest
}: ComponentProps<"select"> & Dense) {
  return (
    <span className={cn("relative inline-block", className)}>
      <select
        className={cn(
          CONTROL,
          "appearance-none rounded-sm pr-8",
          dense ? "h-8 pl-2.5 text-[13px]" : "h-10 pl-3 text-sm",
        )}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown
        size={16}
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-ink-2"
      />
    </span>
  );
}

type CheckboxProps = Omit<ComponentProps<"input">, "type" | "onChange"> & {
  label?: ReactNode;
  onChange?: (checked: boolean) => void;
};

export function Checkbox({ label, onChange, className, ...rest }: CheckboxProps) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-sm has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40", className)}>
      <input type="checkbox" className="peer sr-only" onChange={(e) => onChange?.(e.target.checked)} {...rest} />
      <span
        aria-hidden
        className="grid size-[18px] shrink-0 place-items-center rounded-[5px] border-[1.5px] border-ink bg-surface text-white transition-colors peer-checked:bg-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink [&>svg]:opacity-0 peer-checked:[&>svg]:opacity-100"
      >
        <Check size={13} strokeWidth={3} />
      </span>
      {label}
    </label>
  );
}

// A label + one control + optional hint and error. The label element wraps the control, so
// they are linked without ids.
export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label className="block space-y-1.5">
        <span className="block text-[13px] font-medium text-ink">{label}</span>
        {children}
      </label>
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && (
        <p role="alert" className="text-xs font-medium text-neg">
          {error}
        </p>
      )}
    </div>
  );
}
