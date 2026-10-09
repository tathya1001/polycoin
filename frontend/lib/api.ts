// Client-side fetch wrapper. Only call it from client components or event handlers,
// because it reads document.cookie and uses window.location.

const API = "/api/accounts";

// 401 on these means "bad credentials / no session", not "access token expired",
// so we must never try to refresh and retry them.
const NO_REFRESH_PREFIXES = [
  `${API}/login/`,
  `${API}/register/`,
  `${API}/refresh/`,
  `${API}/logout/`,
];

const SAFE_METHODS = ["GET", "HEAD", "OPTIONS"];

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split("; ")) {
    const i = part.indexOf("=");
    if (i === -1) continue;
    if (part.slice(0, i) === name) return decodeURIComponent(part.slice(i + 1));
  }
  return null;
}

// Django only sets the csrftoken cookie when a view asks for it, so fetch it on demand.
async function ensureCsrfToken(): Promise<string> {
  const existing = getCookie("csrftoken");
  if (existing) return existing;

  await fetch(`${API}/csrf/`, { credentials: "include" });
  const token = getCookie("csrftoken");
  if (!token) throw new Error("Could not obtain a CSRF token");
  return token;
}

// One shared in-flight refresh. If several requests get a 401 at the same moment,
// they all await the same promise. A second refresh would reuse the already-rotated
// (blacklisted) refresh token, get a 401, and log the user out for no reason.
let refreshPromise: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        // Plain fetch, not apiFetch: a failed refresh must not trigger another refresh.
        const res = await fetch(`${API}/refresh/`, {
          method: "POST",
          headers: { "X-CSRFToken": await ensureCsrfToken() },
          credentials: "include",
        });
        return res.ok;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshPromise = null; // allow a later expiry to refresh again
    });
  }
  return refreshPromise;
}

function redirectToLogin() {
  const path = window.location.pathname;
  if (path !== "/login" && path !== "/register") {
    // Full page load on purpose: clears in-memory state once the session is gone.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";

  }
}

async function send(
  path: string,
  options: RequestInit,
  canRetry: boolean,
): Promise<Response> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);

  // Only default to JSON for string bodies; FormData (file uploads) must set
  // its own multipart boundary, so we leave Content-Type alone for it.
  if (typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!SAFE_METHODS.includes(method)) {
    headers.set("X-CSRFToken", await ensureCsrfToken());
  }

  const res = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "include",
  });

  const isAuthEndpoint = NO_REFRESH_PREFIXES.some((p) => path.startsWith(p));
  if (res.status === 401 && canRetry && !isAuthEndpoint) {
    if (await refreshSession()) {
      return send(path, options, false); // retry exactly once
    }
    redirectToLogin();
  }
  return res;
}

export async function apiFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  return send(path, options, true);
}
