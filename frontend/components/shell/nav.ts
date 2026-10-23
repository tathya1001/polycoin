import {
  ArrowLeftRight,
  FileUp,
  LayoutDashboard,
  MessageSquareText,
  Settings2,
  Sparkles,
  Tag,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };
export type NavGroup = { label: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Insights",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/ask", label: "Ask", icon: MessageSquareText },
    ],
  },
  {
    label: "Money",
    items: [
      { href: "/transactions", label: "Transactions", icon: ArrowLeftRight },
      { href: "/transactions/import", label: "Import", icon: FileUp },
      { href: "/transactions/categorize", label: "Categorize", icon: Sparkles },
    ],
  },
  {
    label: "Organise",
    items: [{ href: "/categories", label: "Categories", icon: Tag }],
  },
];

export const SETTINGS_ITEM: NavItem = { href: "/settings", label: "Settings", icon: Settings2 };

const ALL_ITEMS = [...NAV_GROUPS.flatMap((g) => g.items), SETTINGS_ITEM];

// The longest matching link is the current page ("/transactions/import" beats "/transactions").
export function activeHref(pathname: string): string | undefined {
  return ALL_ITEMS.filter((i) => pathname === i.href || pathname.startsWith(`${i.href}/`)).sort(
    (a, b) => b.href.length - a.href.length,
  )[0]?.href;
}
