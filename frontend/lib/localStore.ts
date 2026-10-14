// A tiny store for per-device choices kept in localStorage, readable with useSyncExternalStore.
// The server render always uses `fallback`, so the first client render matches it; React then
// switches to the stored value without a hydration mismatch.
//
//   const collapsed = createLocalStore("key", (raw) => raw === "1", (v) => (v ? "1" : "0"), false);
//   const value = useSyncExternalStore(collapsed.subscribe, collapsed.get, collapsed.getServer);

import { recall, remember } from "@/lib/storage";

export function createLocalStore<T>(
  key: string,
  parse: (raw: string | null) => T,
  serialize: (value: T) => string,
  fallback: T,
) {
  let current: T | undefined; // read lazily, then kept in memory (localStorage may be blocked)
  const listeners = new Set<() => void>();

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    get(): T {
      if (current === undefined) current = parse(recall(key));
      return current;
    },
    getServer(): T {
      return fallback;
    },
    set(value: T) {
      current = value;
      remember(key, serialize(value));
      listeners.forEach((listener) => listener());
    },
  };
}
