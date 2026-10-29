"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { apiFetch } from "@/lib/api";
import { createLocalStore } from "@/lib/localStore";
import { DEFAULT_FONT, isFontChoice } from "@/lib/fonts";
import { applyTheme, DARK_QUERY, DEFAULT_THEME, isThemeChoice, resolveTheme, type ResolvedTheme } from "@/lib/theme";
import type { FontChoice, Preferences } from "@/lib/types";

const DEFAULT_PREFS: Preferences = { font: DEFAULT_FONT, chart_quality: "quality", theme: DEFAULT_THEME };

function parsePreferences(data: unknown): Preferences {
  const raw = data as { font?: unknown; chart_quality?: unknown; theme?: unknown } | null;
  return {
    font: isFontChoice(raw?.font) ? raw.font : DEFAULT_FONT,
    chart_quality: raw?.chart_quality === "performance" ? "performance" : "quality",
    theme: isThemeChoice(raw?.theme) ? raw.theme : DEFAULT_THEME,
  };
}

// The device's light/dark setting, live (it can change while the app is open, e.g. at sunset).
function subscribeToDeviceTheme(onChange: () => void) {
  const query = window.matchMedia(DARK_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
const deviceIsDark = () => window.matchMedia(DARK_QUERY).matches;
const deviceIsDarkOnServer = () => false;

// The cached copy of the preferences. app/layout.tsx reads the same key before first paint.
const preferencesStore = createLocalStore<Preferences>(
  "polycoin.prefs",
  (raw) => {
    try {
      return raw ? parsePreferences(JSON.parse(raw)) : DEFAULT_PREFS;
    } catch {
      return DEFAULT_PREFS; // a corrupt cache is just ignored
    }
  },
  (value) => JSON.stringify(value),
  DEFAULT_PREFS,
);

type Session = {
  email: string | null;
  preferences: Preferences;
  // The colour mode on screen: "Match device" already turned into Light or Dark.
  theme: ResolvedTheme;
  // Saves a change; resolves false (and rolls back) if the server refused it.
  updatePreferences: (change: Partial<Preferences>) => Promise<boolean>;
  // Reads them again from the server, after something else changed them (a backup restore).
  reloadPreferences: () => Promise<void>;
};

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside <SessionProvider>");
  return session;
}

function applyFont(font: FontChoice) {
  if (font === DEFAULT_FONT) delete document.documentElement.dataset.font;
  else document.documentElement.dataset.font = font;
}

function applyLook(preferences: Preferences) {
  applyFont(preferences.font);
  applyTheme(resolveTheme(preferences.theme, deviceIsDark()));
}

function adoptPreferences(data: unknown) {
  const next = parsePreferences(data);
  preferencesStore.set(next);
  applyLook(next);
}

// Who is signed in and how they like the app to look. Preferences live on the server (so they
// follow the user across devices); localStorage only keeps a copy so the font and the colour
// mode are right on the very first paint.
export function SessionProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const preferences = useSyncExternalStore(preferencesStore.subscribe, preferencesStore.get, preferencesStore.getServer);
  const prefersDark = useSyncExternalStore(subscribeToDeviceTheme, deviceIsDark, deviceIsDarkOnServer);
  const theme = resolveTheme(preferences.theme, prefersDark);

  // "Match device" follows the device while the app is open. The page itself is only touched on
  // events (here, and when preferences arrive or change), never from a render: the first render
  // during hydration sees the server's defaults and would undo the pre-paint script.
  useEffect(
    () => subscribeToDeviceTheme(() => applyTheme(resolveTheme(preferencesStore.get().theme, deviceIsDark()))),
    [],
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [me, prefs] = await Promise.all([
          apiFetch("/api/accounts/me/"),
          apiFetch("/api/accounts/preferences/"),
        ]);
        if (cancelled) return;
        if (me.ok) setEmail((await me.json()).email ?? null);
        if (prefs.ok) {
          const data = await prefs.json();
          if (!cancelled) adoptPreferences(data);
        }
      } catch {
        // offline: keep the cached look
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const updatePreferences = useCallback(
    async (change: Partial<Preferences>) => {
      const previous = preferences;
      const next = { ...preferences, ...change };
      preferencesStore.set(next); // optimistic: the font and colours change instantly
      applyLook(next);
      try {
        const res = await apiFetch("/api/accounts/preferences/", {
          method: "PATCH",
          body: JSON.stringify(change),
        });
        if (res.ok) return true;
      } catch {
        // fall through to the rollback
      }
      preferencesStore.set(previous);
      applyLook(previous);
      return false;
    },
    [preferences],
  );

  const reloadPreferences = useCallback(async () => {
    try {
      const res = await apiFetch("/api/accounts/preferences/");
      if (res.ok) adoptPreferences(await res.json());
    } catch {
      // offline: keep the current look
    }
  }, []);

  const value = useMemo(
    () => ({ email, preferences, theme, updatePreferences, reloadPreferences }),
    [email, preferences, theme, updatePreferences, reloadPreferences],
  );
  return <SessionContext value={value}>{children}</SessionContext>;
}
