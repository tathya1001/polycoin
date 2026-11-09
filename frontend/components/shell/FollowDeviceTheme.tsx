"use client";

import { useEffect } from "react";
import { PREFERENCES_KEY, recall } from "@/lib/storage";

// The colour modes a user can pin. Anything else, or nothing cached, means "Match device". Keep in
// step with lib/theme.ts (THEME_OPTIONS) and the pre-paint script in app/layout.tsx.
const PINNED = ["classic", "light", "dark"];

function pinnedTheme(): boolean {
  try {
    const theme = JSON.parse(recall(PREFERENCES_KEY) ?? "{}")?.theme;
    return PINNED.includes(theme);
  } catch {
    return false; // a corrupt cache counts as no choice
  }
}

// For the pages without a session (home and sign-in): when the colour mode comes from the device,
// follow the device if it switches between light and dark while the page is open. The pre-paint
// script picked the starting mode. Kept apart from the session code so these pages stay light.
export function FollowDeviceTheme() {
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => {
      if (!pinnedTheme()) document.documentElement.dataset.theme = query.matches ? "dark" : "light";
    };
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, []);
  return null;
}
