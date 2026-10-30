import type { ComponentProps } from "react";
import { cn } from "@/lib/cn";
import { signedMoney } from "@/lib/format";

// <Table><thead><Tr><Th/>…</Tr></thead><tbody><Tr><Td/>…</Tr></tbody></Table>
export function Table({ className, children, ...rest }: ComponentProps<"table">) {
  return (
    <div className="overflow-x-auto rounded-md border-[1.5px] border-line bg-surface shadow-card">
      <table className={cn("w-full border-collapse text-sm", className)} {...rest}>
        {children}
      </table>
    </div>
  );
}

export function Tr({ className, ...rest }: ComponentProps<"tr">) {
  return (
    <tr
      className={cn("border-b border-hairline transition-colors last:border-b-0 hover:bg-canvas/70", className)}
      {...rest}
    />
  );
}

export function Th({ align = "left", className, ...rest }: ComponentProps<"th"> & { align?: "left" | "right" }) {
  return (
    <th
      className={cn(
        "border-b-[1.5px] border-line bg-wash px-3 py-2.5 text-xs font-semibold tracking-wide whitespace-nowrap text-ink-2 uppercase",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
      {...rest}
    />
  );
}

export function Td({ align = "left", className, ...rest }: ComponentProps<"td"> & { align?: "left" | "right" }) {
  return <td className={cn("px-3 py-2.5 align-middle", align === "right" && "text-right tabular-nums", className)} {...rest} />;
}

// +₹1,200.00 in green for money in, -₹450.00 in red for money out.
export function MoneyCell({
  value,
  type,
  className,
}: {
  value: string;
  type: "credit" | "debit";
  className?: string;
}) {
  return (
    <Td
      align="right"
      title={signedMoney(value, type)}
      className={cn("font-medium whitespace-nowrap", type === "credit" ? "text-pos" : "text-neg", className)}
    >
      {signedMoney(value, type)}
    </Td>
  );
}
