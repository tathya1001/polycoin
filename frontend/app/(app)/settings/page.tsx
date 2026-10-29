"use client";

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Check, Gem, LogOut, Trash2, Zap } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { FONT_OPTIONS, fontFamilyOf, type FontKind } from "@/lib/fonts";
import { THEME_OPTIONS, type ResolvedTheme, type ThemeChoice } from "@/lib/theme";
import type { ChartQuality, Preferences } from "@/lib/types";
import { useSession } from "@/components/shell/Session";
import { BackupCard } from "@/components/settings/BackupCard";
import { DeleteDataDialog } from "@/components/settings/DeleteDataDialog";
import { Button } from "@/components/ui/Button";
import { Badge, Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";

const KIND_LABELS: Record<FontKind, string> = { sans: "Sans", serif: "Serif", mono: "Mono" };

// Charts are drawn as SVG (sharp vector shapes) or on a canvas (a grid of pixels, faster when
// a chart has thousands of points). See components/charts/EChart.tsx.
const CHART_QUALITIES: { id: ChartQuality; name: string; blurb: string; icon: ReactNode }[] = [
  {
    id: "quality",
    name: "High quality",
    blurb: "Vector (SVG) charts: razor sharp at any zoom and screen scaling. The default.",
    icon: <Gem size={20} strokeWidth={1.75} aria-hidden />,
  },
  {
    id: "performance",
    name: "Performance",
    blurb: "Canvas charts: a little softer when zoomed, but smoother with thousands of points.",
    icon: <Zap size={20} strokeWidth={1.75} aria-hidden />,
  },
];

export default function Settings() {
  const router = useRouter();
  const toast = useToast();
  const { email, preferences, updatePreferences } = useSession();
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  async function choose(change: Partial<Preferences>, failure: string) {
    const ok = await updatePreferences(change);
    if (!ok) toast.error(failure);
  }

  async function logOut() {
    await apiFetch("/api/accounts/logout/", { method: "POST" });
    router.push("/login");
  }

  return (
    <>
      <PageHeader title="Settings" subtitle="Make Polycoin look the way you like. Saved to your account, so it follows you." />

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Appearance</h2>
        <p className="mb-3 text-sm font-medium">Colour mode</p>
        <div role="radiogroup" aria-label="Colour mode" className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {THEME_OPTIONS.map((theme) => (
            <ChoiceCard
              key={theme.id}
              selected={preferences.theme === theme.id}
              onSelect={() =>
                preferences.theme !== theme.id && choose({ theme: theme.id }, "Could not save your colour mode. Try again.")
              }
            >
              <ThemePreview theme={theme.id} />
              <span className="mt-3 block text-lg font-semibold">{theme.name}</span>
              <span className="mt-1 block text-sm text-ink-2">{theme.blurb}</span>
            </ChoiceCard>
          ))}
        </div>
        <p className="mb-3 text-sm font-medium">Font</p>
        <div role="radiogroup" aria-label="Font" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FONT_OPTIONS.map((font) => {
            const family = fontFamilyOf(font);
            return (
              <ChoiceCard
                key={font.id}
                selected={preferences.font === font.id}
                onSelect={() =>
                  preferences.font !== font.id && choose({ font: font.id }, "Could not save your font. Try again.")
                }
              >
                <span className="block truncate text-3xl font-semibold tracking-tight" style={{ fontFamily: family }}>
                  ₹42,310.00
                </span>
                <span className="mt-3 flex items-center gap-2">
                  <span className="text-lg font-semibold" style={{ fontFamily: family }}>
                    {font.name}
                  </span>
                  <Badge>{KIND_LABELS[font.kind]}</Badge>
                </span>
              </ChoiceCard>
            );
          })}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Charts</h2>
        <div role="radiogroup" aria-label="Chart rendering" className="grid gap-4 sm:grid-cols-2">
          {CHART_QUALITIES.map((quality) => (
            <ChoiceCard
              key={quality.id}
              selected={preferences.chart_quality === quality.id}
              onSelect={() =>
                preferences.chart_quality !== quality.id &&
                choose({ chart_quality: quality.id }, "Could not save the chart setting. Try again.")
              }
            >
              <span className="flex items-center gap-2 text-lg font-semibold">
                {quality.icon}
                {quality.name}
              </span>
              <span className="mt-2 block text-sm text-ink-2">{quality.blurb}</span>
            </ChoiceCard>
          ))}
        </div>
        <p className="mt-3 text-sm text-muted">Applies right away. Charts redraw the moment you switch.</p>
      </section>

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Your data</h2>
        <BackupCard />
        <Card className="mt-4 flex flex-wrap items-center justify-between gap-4 border-neg">
          <div className="max-w-xl">
            <p className="font-medium">Delete all my data</p>
            <p className="text-sm text-ink-2">
              Removes your transactions, dashboards and own categories. Your account and these settings stay.
              You will be asked for your password.
            </p>
          </div>
          <Button variant="danger" icon={<Trash2 size={16} />} onClick={() => setConfirmingDelete(true)}>
            Delete all my data
          </Button>
        </Card>
        <DeleteDataDialog open={confirmingDelete} onClose={() => setConfirmingDelete(false)} />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Account</h2>
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm text-ink-2">Signed in as</p>
            <p className="font-medium">{email ?? "…"}</p>
          </div>
          <Button icon={<LogOut size={16} />} onClick={logOut}>
            Log out
          </Button>
        </Card>
      </section>
    </>
  );
}

// A thumbnail of each mode, drawn in that mode's own colours whatever mode is on screen (so it
// can't use the page's tokens). Values from app/globals.css.
const PREVIEW: Record<ResolvedTheme, { canvas: string; surface: string; ink: string; fill: string; line: string; muted: string; shadow: string }> = {
  classic: { canvas: "#f7f6f2", surface: "#f7f6f2", ink: "#111111", fill: "#111111", line: "#111111", muted: "#e4e2dc", shadow: "#111111" },
  light: { canvas: "#fbfbf9", surface: "#fbfbf9", ink: "#2b2b2e", fill: "#2b2b2e", line: "#e4e3df", muted: "#eeede9", shadow: "#d2d1cc" },
  dark: { canvas: "#0f0f10", surface: "#0f0f10", ink: "#d6d6d8", fill: "#2e2e33", line: "#2c2c2f", muted: "#222224", shadow: "#000000" },
};

function MiniPage({ theme }: { theme: ResolvedTheme }) {
  const c = PREVIEW[theme];
  return (
    <span className="flex h-full flex-1 flex-col gap-1.5 p-2.5" style={{ background: c.canvas }}>
      <span className="h-2 w-10 rounded-full" style={{ background: c.ink }} />
      <span
        className="flex flex-1 items-end gap-1 rounded-[5px] p-1.5"
        style={{ background: c.surface, border: `1px solid ${c.line}` }}
      >
        {[45, 80, 60].map((height, i) => (
          <span key={i} className="w-2.5 rounded-t-[2px]" style={{ height: `${height}%`, background: ["#2A78D6", "#EB6834", "#1BAF7A"][i] }} />
        ))}
        <span className="ml-auto h-1.5 w-8 self-center rounded-full" style={{ background: c.muted }} />
      </span>
      <span
        className="h-3 w-12 rounded-[4px]"
        style={{ background: c.fill, boxShadow: `2px 2px 0 ${c.shadow}` }}
      />
    </span>
  );
}

function ThemePreview({ theme }: { theme: ThemeChoice }) {
  return (
    <span aria-hidden className="flex h-24 overflow-hidden rounded-sm border border-line">
      {theme === "system" ? (
        <>
          <MiniPage theme="light" />
          <MiniPage theme="dark" />
        </>
      ) : (
        <MiniPage theme={theme} />
      )}
    </span>
  );
}

// One option in a radio group, drawn as a card. The selected one has a tick and a deeper shadow.
function ChoiceCard({ selected, onSelect, children }: { selected: boolean; onSelect: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "relative rounded-md border-[1.5px] border-edge bg-surface p-5 text-left transition-[transform,box-shadow] duration-150",
        selected ? "shadow-hard" : "shadow-hard-sm hover:-translate-y-px hover:shadow-hard",
      )}
    >
      {selected && (
        <span className="absolute top-3 right-3 grid size-6 place-items-center rounded-full bg-fill text-on-fill">
          <Check size={14} strokeWidth={3} aria-hidden />
        </span>
      )}
      {children}
    </button>
  );
}
