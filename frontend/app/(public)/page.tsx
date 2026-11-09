import Link from "next/link";
import { Suspense } from "react";
import { DeletedNotice } from "@/components/auth/DeletedNotice";
import { DashboardPreview } from "@/components/home/DashboardPreview";
import { Logo } from "@/components/shell/Logo";
import { buttonClass } from "@/components/ui/Button";

// What the app promises about the user's data, said once, at the foot of the page.
const PROMISES = ["Encrypted with your password", "AI runs on your own computer", "Delete everything, any time"];

// Visitors only: proxy.ts sends signed-in users straight to /dashboard. Deleting an account
// (Settings) lands here with ?account=deleted.
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-5 sm:px-6">
      <nav className="flex items-center justify-between">
        <Logo />
        <Link href="/login" className={buttonClass("ghost", "md")}>
          Log in
        </Link>
      </nav>

      <section className="pt-14 pb-10 sm:pt-20">
        <Suspense>
          <DeletedNotice />
        </Suspense>
        <h1 className="max-w-[15ch] text-[44px] leading-[1.02] font-semibold tracking-tight text-balance sm:text-7xl">
          Your bank statement, seen from every angle.
        </h1>
        <p className="mt-6 max-w-xl text-lg text-ink-2">
          Import a statement. MoneyAngle sorts every transaction and builds your dashboards.
        </p>
        <Link href="/register" className={buttonClass("primary", "md", "mt-8 h-12 px-6 text-base")}>
          Create account
        </Link>
      </section>

      <DashboardPreview />

      <ul className="mt-10 flex flex-wrap gap-x-8 gap-y-2 border-t-[1.5px] border-hairline py-6 text-sm text-ink-2">
        {PROMISES.map((promise) => (
          <li key={promise} className="flex items-center gap-2.5">
            <span aria-hidden className="size-1.5 rounded-full bg-ink" />
            {promise}
          </li>
        ))}
      </ul>
    </main>
  );
}
