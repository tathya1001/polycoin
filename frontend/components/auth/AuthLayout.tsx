import type { ReactNode } from "react";
import Link from "next/link";
import { Logo } from "@/components/shell/Logo";
import { WakeServer } from "./WakeServer";

// One centred column: the logo (a link home), the title, the form and its links. Nothing else, so
// the form is the whole page.
export function AuthLayout({
  title,
  subtitle,
  footer,
  children,
}: {
  title: string;
  subtitle?: string;
  footer: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12 sm:px-6">
      <WakeServer />
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-10 inline-flex" aria-label="MoneyAngle home">
          <Logo />
        </Link>
        <h1 className="text-[28px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-ink-2">{subtitle}</p>}
        <div className="mt-7">{children}</div>
        {footer && <p className="mt-6 text-sm text-ink-2">{footer}</p>}
      </div>
    </main>
  );
}
