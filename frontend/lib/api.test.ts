import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, REFRESH_RETRY_DELAYS_MS } from "./api";

// Answers are queued per URL; each fetch to that URL takes the next one ("network" = a failure).
type Answer = number | "network";
let queues: Record<string, Answer[]>;
let calls: string[];
let location: { pathname: string; href: string };

function answer(status: number) {
  return new Response(JSON.stringify({ detail: `status ${status}` }), { status });
}

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  location = { pathname: "/dashboard", href: "/dashboard" };
  vi.stubGlobal("window", { location });
  vi.stubGlobal("document", { cookie: "csrftoken=token" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      const next = queues[url]?.shift();
      if (next === undefined) throw new Error(`unexpected fetch ${url}`);
      if (next === "network") throw new TypeError("Failed to fetch");
      return answer(next);
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ME = "/api/accounts/me/";
const REFRESH = "/api/accounts/refresh/";

async function run(path = ME) {
  const pending = apiFetch(path);
  await vi.runAllTimersAsync(); // let every retry delay pass
  return pending;
}

describe("an expired access token", () => {
  it("is refreshed and the request retried once", async () => {
    queues = { [ME]: [401, 200], [REFRESH]: [200] };
    expect((await run()).status).toBe(200);
    expect(calls).toEqual([ME, REFRESH, ME]);
    expect(location.href).toBe("/dashboard");
  });

  it("logs out only when the server rejects the session", async () => {
    queues = { [ME]: [401], [REFRESH]: [401] };
    await run();
    expect(location.href).toBe("/login");
    expect(calls.filter((c) => c === REFRESH)).toHaveLength(1); // a rejection is final: no retries
  });
});

describe("a server that is waking up", () => {
  it("is waited for: the refresh is retried until it answers", async () => {
    queues = { [ME]: [401, 200], [REFRESH]: [502, 504, "network", 503, 200] };
    expect((await run()).status).toBe(200);
    expect(location.href).toBe("/dashboard"); // still signed in
  });

  it("treats a rate limit as temporary, not as a lost session", async () => {
    queues = { [ME]: [401, 200], [REFRESH]: [429, 200] };
    expect((await run()).status).toBe(200);
    expect(location.href).toBe("/dashboard");
  });

  it("keeps the user signed in and says so when it never answers", async () => {
    const attempts = REFRESH_RETRY_DELAYS_MS.length + 1;
    queues = { [ME]: [401], [REFRESH]: Array<Answer>(attempts).fill(503) };

    const res = await run();

    expect(res.status).toBe(503);
    expect((await res.json()).detail).toMatch(/waking up/);
    expect(calls.filter((c) => c === REFRESH)).toHaveLength(attempts);
    expect(location.href).toBe("/dashboard"); // not sent to /login
  });
});

describe("several requests expiring together", () => {
  it("share one refresh (a second would reuse the rotated token)", async () => {
    const OTHER = "/api/accounts/preferences/";
    queues = { [ME]: [401, 200], [OTHER]: [401, 200], [REFRESH]: [200] };

    const both = Promise.all([apiFetch(ME), apiFetch(OTHER)]);
    await vi.runAllTimersAsync();
    const [a, b] = await both;

    expect([a.status, b.status]).toEqual([200, 200]);
    expect(calls.filter((c) => c === REFRESH)).toHaveLength(1);
  });
});
