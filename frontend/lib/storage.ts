// localStorage can be missing or throw (private windows, blocked site data): it is a
// convenience, never something a page depends on.

export function recall(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // ignore: the choice just won't survive a reload
  }
}
