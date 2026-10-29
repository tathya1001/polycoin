"use client";

import { useEffect } from "react";
import { pingServer } from "@/lib/ping";

// The backend sleeps when nobody uses it, and waking takes up to a minute. The sign-in pages
// send a cheap ping as soon as they open, so the server wakes while the user types instead of
// after they press the button.
export function WakeServer() {
  useEffect(() => {
    pingServer();
  }, []);
  return null;
}
