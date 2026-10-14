import type { ComponentProps, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const BASE =
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap font-medium select-none " +
  "border-[1.5px] transition-[transform,box-shadow,background-color,opacity] duration-150 ease-out " +
  "disabled:pointer-events-none disabled:opacity-40";

// The "raised" feel: hover lifts 1px, press drops 2px and loses the shadow (pushed in).
const RAISED =
  "hover:-translate-y-px active:translate-x-0.5 active:translate-y-0.5 active:shadow-none";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: `${RAISED} border-ink bg-ink text-white shadow-hard-sm hover:shadow-hard`,
  secondary: `${RAISED} border-ink bg-surface text-ink shadow-hard-sm hover:shadow-hard`,
  danger: `${RAISED} border-neg bg-surface text-neg shadow-[2px_2px_0_0_#dc2626] hover:shadow-[4px_4px_0_0_#dc2626]`,
  ghost: "border-transparent bg-transparent text-ink hover:bg-wash active:bg-hairline",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 rounded-sm px-3 text-[13px]",
  md: "h-10 rounded-md px-4 text-sm",
};

// Class string for anything that must LOOK like a button but isn't one (a next/link).
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string) {
  return cn(BASE, VARIANTS[variant], SIZES[size], extra);
}

type ButtonProps = ComponentProps<"button"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? <Loader2 size={16} className="animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

type IconButtonProps = Omit<ComponentProps<"button">, "children"> & {
  label: string; // required: an icon alone has no accessible name
  icon: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export function IconButton({ label, icon, variant = "ghost", size = "md", className, type = "button", ...rest }: IconButtonProps) {
  const square = size === "sm" ? "size-8 px-0!" : "size-10 px-0!";
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={buttonClass(variant, size, cn(square, className))}
      {...rest}
    >
      {icon}
    </button>
  );
}
