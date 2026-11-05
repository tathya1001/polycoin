import Link from "next/link";
import { Suspense } from "react";
import { ArrowRight, BarChart3, Lock, Sparkles } from "lucide-react";
import { DeletedNotice } from "@/components/auth/DeletedNotice";
import { Wordmark } from "@/components/shell/Logo";
import { buttonClass } from "@/components/ui/Button";

const FEATURES = [
  { icon: Sparkles, title: "Sorted for you", text: "A local AI model proposes categories. You approve them." },
  { icon: BarChart3, title: "Dashboards you shape", text: "Drag, resize and recolour chart panels until it looks right." },
  {
    icon: Lock,
    title: "Locked with your password",
    text: "Names, amounts and balances are encrypted with a key that only your password, or your recovery key, can open.",
  },
];

// Visitors only: proxy.ts sends signed-in users straight to /dashboard. Deleting an account
// (Settings) lands here with ?account=deleted.
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-6 py-6">
      <nav className="flex items-center justify-between">
        <span className="flex items-center gap-2.5">
          <Wordmark />
        </span>
        <span className="flex items-center gap-2">
          <Link href="/login" className={buttonClass("ghost", "md")}>
            Log in
          </Link>
          <Link href="/register" className={buttonClass("primary", "md")}>
            Create account
          </Link>
        </span>
      </nav>

      <section className="flex flex-1 flex-col justify-center py-16">
        <Suspense>
          <DeletedNotice />
        </Suspense>
        <h1 className="max-w-3xl text-5xl leading-[1.02] font-semibold tracking-tight sm:text-7xl">
          Your bank statement, <span className="rounded-md bg-fill px-3 text-on-fill">finally</span> readable.
        </h1>
        <p className="mt-6 max-w-xl text-lg text-ink-2">
          Import a statement, let MoneyAngle sort every transaction, and build colourful dashboards that show where
          the money went. Locked with your password, and yours to delete at any time.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/register" className={buttonClass("primary", "md", "h-12 px-6 text-base")}>
            Get started <ArrowRight size={18} aria-hidden />
          </Link>
          <Link href="/login" className={buttonClass("secondary", "md", "h-12 px-6 text-base")}>
            I have an account
          </Link>
        </div>

        <ul className="mt-16 grid gap-4 sm:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <li key={title} className="rounded-md border-[1.5px] border-line bg-surface p-5 shadow-card">
              <Icon size={22} strokeWidth={1.75} aria-hidden />
              <h2 className="mt-3 font-semibold">{title}</h2>
              <p className="mt-1 text-ink-2">{text}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
