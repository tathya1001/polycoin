"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/transactions", label: "Transactions" },
  { href: "/transactions/import", label: "Import" },
  { href: "/transactions/categorize", label: "Categorize" },
  { href: "/categories", label: "Categories" },
];

// Pages a signed-out visitor sees: no app navigation there.
const PUBLIC_PATHS = ["/", "/login", "/register"];

export default function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();
  if (PUBLIC_PATHS.includes(pathname)) return null;

  async function logOut() {
    await apiFetch("/api/accounts/logout/", { method: "POST" });
    router.push("/login");
  }

  // The longest matching link is the current page ("/transactions/import" beats "/transactions").
  const current = LINKS.filter((l) => pathname === l.href || pathname.startsWith(`${l.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    <header className="sticky top-0 z-30 border-b border-gray-200 bg-background/95 backdrop-blur dark:border-gray-800">
      <nav className="mx-auto flex max-w-350 flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-sm">
        <Link href="/dashboard" className="mr-2 font-semibold tracking-tight">
          Polycoin
        </Link>
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            aria-current={current === link.href ? "page" : undefined}
            className={
              current === link.href
                ? "font-medium underline underline-offset-4"
                : "text-gray-600 hover:text-current dark:text-gray-400"
            }
          >
            {link.label}
          </Link>
        ))}
        <button onClick={logOut} className="ml-auto text-gray-600 hover:text-current dark:text-gray-400">
          Log out
        </button>
      </nav>
    </header>
  );
}
