"use client";

import { useEffect } from "react";

// The backend sleeps when nobody uses it, and waking takes up to a minute. The sign-in pages
// send a cheap ping as soon as they open, so the server wakes while the user types instead of
// after they press the button. The ping touches no database and its result is not needed.
export function WakeServer() {
  useEffect(() => {
    fetch("/api/ping/", { cache: "no-store" }).catch(() => {});
  }, []);
  return null;
}
