// The one place money is formatted. Money arrives as a decimal string ("1234.50") or a number;
// Number() is only for display, never for arithmetic that gets saved.

import type { Cell } from "@/lib/types";

const RUPEES = { minimumFractionDigits: 2, maximumFractionDigits: 2 } as const;

// "₹1,234.50", or "–" when there is no value.
export function money(value: Cell | undefined): string {
  if (value === null || value === undefined || value === "") return "–";
  return `₹${Number(value).toLocaleString("en-IN", RUPEES)}`;
}

// "+₹1,234.50" for money in, "-₹1,234.50" for money out. Amounts are stored positive; the
// sign lives in txn_type.
export function signedMoney(value: Cell | undefined, txnType: "credit" | "debit"): string {
  return `${txnType === "credit" ? "+" : "-"}${money(value)}`;
}

const compactFormat = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

// "₹1.2L", "42.3K": for chart axes and tight spaces.
export function compactNumber(value: number): string {
  return compactFormat.format(value);
}
