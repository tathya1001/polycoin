"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { cn } from "@/lib/cn";
import { createLocalStore } from "@/lib/localStore";
import { IconButton } from "@/components/ui/Button";
import { LogoMark, Wordmark } from "@/components/shell/Logo";
import { Sidebar } from "@/components/shell/Sidebar";

// Whether the desktop sidebar is folded to an icon rail: a per-device convenience.
const collapsedStore = createLocalStore("polycoin.sidebar.collapsed", (raw) => raw === "1", (v) => (v ? "1" : "0"), false);

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const collapsed = useSyncExternalStore(collapsedStore.subscribe, collapsedStore.get, collapsedStore.getServer);

  // The mobile drawer is open for the page it was opened on, so navigating closes it.
  const [openedOn, setOpenedOn] = useState<string | null>(null);
  const mobileOpen = openedOn === pathname;

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenedOn(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  function toggleCollapsed() {
    collapsedStore.set(!collapsed);
  }

  // Dashboards get the whole width; every other page reads best in a narrower column.
  const wide = pathname === "/dashboard";

  return (
    <div className="min-h-screen md:flex md:gap-3 md:p-3">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b-[1.5px] border-line bg-canvas px-3 md:hidden">
        <IconButton label="Open menu" icon={<Menu size={20} />} onClick={() => setOpenedOn(pathname)} />
        <LogoMark size={26} />
        <Wordmark />
      </header>

      {mobileOpen && (
        <div aria-hidden className="fixed inset-0 z-40 bg-ink/35 md:hidden" onClick={() => setOpenedOn(null)} />
      )}
      <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} mobileOpen={mobileOpen} />

      <main className="min-w-0 flex-1 px-4 py-5 md:px-4 md:py-3">
        <div className={cn("mx-auto flex w-full flex-col", wide ? "max-w-[1400px]" : "max-w-5xl")}>{children}</div>
      </main>
    </div>
  );
}
