import type { ReactNode } from "react";
import Link from "next/link";
import { LogoMark, Wordmark } from "@/components/shell/Logo";
import { WakeServer } from "./WakeServer";

// Split screen: a bold ink panel on the left (hidden on phones), the form on the right.
export function AuthLayout({
  title,
  subtitle,
  footer,
  children,
}: {
  title: string;
  subtitle: string;
  footer: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <WakeServer />
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-fill p-12 text-on-fill lg:flex">
        <Link href="/" className="flex items-center gap-3">
          <LogoMark size={36} className="text-on-fill" />
          <Wordmark className="text-xl" />
        </Link>

        <div className="relative z-10 max-w-md">
          <h2 className="text-5xl leading-[1.05] font-semibold tracking-tight">Where did your money go?</h2>
          <p className="mt-5 text-lg text-on-fill/70">
            Import a bank statement, let the app sort it, and build dashboards that answer it.
          </p>
        </div>

        <ChartMotif />
      </aside>

      <section className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-sm">
          <Link href="/" className="mb-10 flex items-center gap-2.5 lg:hidden">
            <LogoMark size={28} />
            <Wordmark />
          </Link>
          <h1 className="text-[28px] font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 mb-7 text-ink-2">{subtitle}</p>
          {children}
          <p className="mt-6 text-sm text-ink-2">{footer}</p>
        </div>
      </section>
    </main>
  );
}

// Decorative: bars and a donut in the chart colours, so the first screen already promises
// colourful dashboards.
function ChartMotif() {
  const bars = [
    { h: 38, c: "#EB6834" },
    { h: 64, c: "#2A78D6" },
    { h: 48, c: "#1BAF7A" },
    { h: 86, c: "#E87BA4" },
    { h: 58, c: "#EDA100" },
    { h: 74, c: "#6250D6" },
  ];
  return (
    <div aria-hidden className="relative z-10 flex items-end gap-6">
      <div className="flex h-28 items-end gap-2.5">
        {bars.map((bar) => (
          <div
            key={bar.c}
            style={{ height: bar.h + "%", backgroundColor: bar.c }}
            className="w-9 rounded-t-sm border-[1.5px] border-white"
          />
        ))}
      </div>
      <svg width="96" height="96" viewBox="0 0 96 96" className="shrink-0">
        <circle cx="48" cy="48" r="34" fill="none" stroke="#EB6834" strokeWidth="18" strokeDasharray="90 124" />
        <circle cx="48" cy="48" r="34" fill="none" stroke="#2A78D6" strokeWidth="18" strokeDasharray="70 144" strokeDashoffset="-90" />
        <circle cx="48" cy="48" r="34" fill="none" stroke="#1BAF7A" strokeWidth="18" strokeDasharray="54 160" strokeDashoffset="-160" />
      </svg>
    </div>
  );
}
