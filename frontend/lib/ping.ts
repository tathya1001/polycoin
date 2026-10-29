// A cheap request that wakes the backend if the free Render service has fallen asleep (waking
// takes up to a minute). /api/ping/ touches no database, so it never wakes Neon, and the answer
// isn't needed: only the request matters.
export function pingServer(): Promise<void> {
  return fetch("/api/ping/", { cache: "no-store" }).then(
    () => undefined,
    () => undefined,
  );
}
