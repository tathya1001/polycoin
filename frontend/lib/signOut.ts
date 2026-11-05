// Leaving the app: on log-out, and after the account is deleted.
//
// The browser keeps a few conveniences in localStorage, and some say something about the user's
// money (a dashboard's filters can hold a merchant name they typed). On a shared computer the
// next person must not find them, so leaving forgets every key the app keeps, then does a full
// page load, which also drops everything that was in memory.

import { apiFetch } from "@/lib/api";
import { forgetAll, STORAGE_PREFIX } from "@/lib/storage";

/** Forget this browser's copy of everything, and go to `to` with a full page load. */
export function leave(to = "/login") {
  forgetAll(STORAGE_PREFIX);
  window.location.href = to; // a full page load on purpose: it clears in-memory state too
}

/** Log out: the server revokes the session and clears its cookies, then the browser forgets. */
export async function signOut() {
  try {
    await apiFetch("/api/accounts/logout/", { method: "POST" });
  } catch {
    // Offline: still forget what this browser holds. The session cookie expires on its own.
  }
  leave();
}
