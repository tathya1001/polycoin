"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { LogoMark, Wordmark } from "@/components/shell/Logo";
import { NAV_GROUPS, SETTINGS_ITEM, activeHref, type NavItem } from "@/components/shell/nav";
import { useSession } from "@/components/shell/Session";

type Props = {
  collapsed: boolean; // only the desktop rail collapses; the mobile drawer is always full
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
};

// A floating, inset panel (12px from the window edges). One black pill glides to the page
// you are on. Below 768px it becomes a slide-over drawer.
export function Sidebar({ collapsed, onToggleCollapsed, mobileOpen }: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const { email } = useSession();
  const current = activeHref(pathname);

  const itemRefs = useRef(new Map<string, HTMLAnchorElement>());
  const [pill, setPill] = useState<{ top: number; height: number } | null>(null);

  // Measure the active item (and re-measure when the rail collapses or the window resizes),
  // then let CSS animate the pill to it.
  useLayoutEffect(() => {
    function measure() {
      const el = current ? itemRefs.current.get(current) : undefined;
      setPill(el ? { top: el.offsetTop, height: el.offsetHeight } : null);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [current, collapsed]);

  async function logOut() {
    await apiFetch("/api/accounts/logout/", { method: "POST" });
    router.push("/login");
  }

  const item = (nav: NavItem) => {
    const Icon = nav.icon;
    const active = current === nav.href;
    return (
      <Link
        key={nav.href}
        href={nav.href}
        ref={(el) => {
          if (el) itemRefs.current.set(nav.href, el);
          else itemRefs.current.delete(nav.href);
        }}
        aria-current={active ? "page" : undefined}
        aria-label={nav.label}
        title={collapsed ? nav.label : undefined}
        className={cn(
          "relative z-10 flex h-10 items-center gap-3 rounded-md px-3.5 text-sm font-medium transition-colors duration-200",
          active ? "text-on-fill" : "text-ink-2 hover:bg-wash hover:text-ink",
        )}
      >
        <Icon size={20} strokeWidth={1.75} className="shrink-0" aria-hidden />
        <Label collapsed={collapsed}>{nav.label}</Label>
      </Link>
    );
  };

  return (
    <aside
      className={cn(
        "fixed top-3 bottom-3 left-3 z-50 flex w-68 flex-col rounded-lg border-[1.5px] border-line bg-surface shadow-pop",
        "transition-[width,transform] duration-300 ease-out",
        "md:sticky md:z-20 md:h-[calc(100dvh-1.5rem)] md:translate-x-0 md:shrink-0 md:self-start",
        collapsed ? "md:w-[72px]" : "md:w-62",
        mobileOpen ? "translate-x-0" : "-translate-x-[130%]",
      )}
    >
      <div className="flex h-16 shrink-0 items-center gap-2.5 px-4">
        <LogoMark size={30} />
        <Label collapsed={collapsed}>
          <Wordmark />
        </Label>
        {!collapsed && (
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            className="ml-auto hidden size-8 shrink-0 place-items-center rounded-sm text-ink-2 transition-colors hover:bg-wash hover:text-ink md:grid"
          >
            <PanelLeftClose size={18} />
          </button>
        )}
      </div>

      {collapsed && (
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label="Expand sidebar"
          title="Expand sidebar"
          className="mx-auto mb-1 hidden size-8 place-items-center rounded-sm text-ink-2 transition-colors hover:bg-wash hover:text-ink md:grid"
        >
          <PanelLeftOpen size={18} />
        </button>
      )}

      <nav aria-label="Main" className="relative flex min-h-0 flex-1 flex-col overflow-x-clip overflow-y-auto px-3 pb-2">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-3 z-0 rounded-md bg-fill"
          style={{
            height: pill?.height ?? 0,
            opacity: pill ? 1 : 0,
            transform: `translateY(${pill?.top ?? 0}px)`,
            transition: "transform 380ms var(--ease-spring), height 200ms ease-out, opacity 150ms",
          }}
        />

        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mt-3 first:mt-1">
            <p
              className={cn(
                "mb-1 px-3.5 text-[11px] font-semibold tracking-wider text-muted uppercase",
                collapsed && "md:mx-2 md:h-px md:overflow-hidden md:bg-hairline md:px-0 md:text-transparent",
              )}
            >
              {group.label}
            </p>
            <div className="space-y-0.5">{group.items.map((nav) => item(nav))}</div>
          </div>
        ))}

        <div className="mt-auto pt-3">{item(SETTINGS_ITEM)}</div>
      </nav>

      <div className="shrink-0 border-t border-hairline p-3">
        <div className="flex h-10 items-center gap-3 px-1.5" title={collapsed ? (email ?? undefined) : undefined}>
          <span
            aria-hidden
            className="grid size-8 shrink-0 place-items-center rounded-full border-[1.5px] border-line bg-wash text-xs font-semibold uppercase"
          >
            {email?.[0] ?? "·"}
          </span>
          <Label collapsed={collapsed}>
            <span className="block max-w-36 truncate text-[13px] text-ink-2">{email ?? "Signed in"}</span>
          </Label>
        </div>
        <button
          type="button"
          onClick={logOut}
          title={collapsed ? "Log out" : undefined}
          aria-label="Log out"
          className="mt-1 flex h-10 w-full items-center gap-3 rounded-md px-3.5 text-sm font-medium text-ink-2 transition-colors duration-200 hover:bg-wash hover:text-ink"
        >
          <LogOut size={20} strokeWidth={1.75} className="shrink-0" aria-hidden />
          <Label collapsed={collapsed}>Log out</Label>
        </button>
      </div>
    </aside>
  );
}

// Text that fades out when the desktop rail is collapsed (the icon stays put).
function Label({ collapsed, children }: { collapsed: boolean; children: ReactNode }) {
  return (
    <span
      className={cn(
        "overflow-hidden whitespace-nowrap transition-opacity duration-200",
        collapsed && "md:pointer-events-none md:w-0 md:opacity-0",
      )}
    >
      {children}
    </span>
  );
}
