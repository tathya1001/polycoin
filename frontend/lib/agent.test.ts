import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentProblem, httpAgentApi, MAX_ROUNDS, runTurn, type AgentApi, type AgentChat } from "./agent";
import type { AgentDashboard, AgentOutcome, AgentResponse } from "./types";

const DASHBOARD: AgentDashboard = {
  filters: { date: { preset: "inherit" }, type: null, categories: [], data_sources: [], merchant_contains: "" },
  parameters: null,
};
const SCHEMA = { type: "object" };
const OPTIONS = { temperature: 0, num_ctx: 4096, num_predict: 400 };
const DONE: AgentOutcome = { kind: "not_a_panel", reason: "A question." };

function chatNeeded(token: string, attempt = 1): AgentResponse {
  return {
    status: "needs_model",
    token,
    progress: { label: attempt > 1 ? "Fixing the panel" : "Reading your request", attempt },
    request: { kind: "chat", messages: [{ role: "user", content: "<request>x</request>" }], format: SCHEMA, options: OPTIONS },
  };
}

function embedNeeded(token: string): AgentResponse {
  return {
    status: "needs_model",
    token,
    progress: { label: "Looking up the merchant", attempt: 1 },
    request: { kind: "embed", model: "nomic-embed-text:latest", text: "search_query: workout" },
  };
}

const done = (token: string, outcome: AgentOutcome = DONE): AgentResponse => ({ status: "done", token, outcome });

/** A fake server that answers each call with the next canned response, and records the calls. */
function fakeApi(responses: AgentResponse[]) {
  const turns: unknown[] = [];
  const steps: unknown[] = [];
  const api: AgentApi = {
    status: vi.fn(),
    turn: vi.fn(async (body) => {
      turns.push(body);
      return responses.shift()!;
    }),
    step: vi.fn(async (body) => {
      steps.push(body);
      return responses.shift()!;
    }),
  };
  return { api, turns, steps };
}

const replyWith = (text: string): AgentChat => vi.fn(async () => text);

describe("runTurn", () => {
  it("relays each chat request to the model and its reply back, until the server is done", async () => {
    const { api, turns, steps } = fakeApi([chatNeeded("t1"), chatNeeded("t2", 2), done("t3")]);
    const chat = vi.fn<AgentChat>().mockResolvedValueOnce("broken").mockResolvedValueOnce('{"kind":"panel"}');
    const progress: unknown[] = [];

    const result = await runTurn({
      api,
      chat,
      message: "spend by category",
      token: "old",
      dashboard: DASHBOARD,
      embedModel: null,
      onProgress: (p) => progress.push(p),
    });

    expect(result).toEqual({ token: "t3", outcome: DONE });
    expect(turns).toEqual([{ message: "spend by category", token: "old", dashboard: DASHBOARD, embed: null }]);
    expect(steps).toEqual([
      { token: "t1", reply: "broken" },
      { token: "t2", reply: '{"kind":"panel"}' },
    ]);
    expect(chat).toHaveBeenCalledWith(
      [{ role: "user", content: "<request>x</request>" }],
      OPTIONS,
      SCHEMA,
      undefined,
    );
    expect(progress).toEqual([
      { label: "Reading your request", attempt: 1 },
      { label: "Fixing the panel", attempt: 2 },
    ]);
  });

  it("embeds a merchant with the user's model, rounding the vector", async () => {
    const { api, turns, steps } = fakeApi([embedNeeded("t1"), done("t2")]);
    const embed = vi.fn(async () => [0.123456789, -0.5]);

    await runTurn({
      api,
      chat: replyWith(""),
      embed,
      message: "workout spend",
      token: null,
      dashboard: DASHBOARD,
      embedModel: { model: "nomic-embed-text:latest", digest: "sha256:abc" },
    });

    expect(turns[0]).toMatchObject({ embed: { model: "nomic-embed-text:latest", digest: "sha256:abc" } });
    expect(embed).toHaveBeenCalledWith("nomic-embed-text:latest", "search_query: workout");
    expect(steps).toEqual([{ token: "t1", vector: [0.12346, -0.5] }]);
  });

  it("without an embedder, announces none and skips a merchant lookup", async () => {
    const { api, turns, steps } = fakeApi([embedNeeded("t1"), done("t2")]);
    await runTurn({
      api,
      chat: replyWith(""),
      message: "workout spend",
      token: null,
      dashboard: DASHBOARD,
      embedModel: { model: "nomic-embed-text:latest", digest: "sha256:abc" },
    });
    expect(turns[0]).toMatchObject({ embed: null });
    expect(steps).toEqual([{ token: "t1", skip: true }]);
  });

  it("cuts a reply longer than the server accepts", async () => {
    const { api, steps } = fakeApi([chatNeeded("t1"), done("t2")]);
    await runTurn({ api, chat: replyWith("x".repeat(5000)), message: "m", token: null, dashboard: DASHBOARD, embedModel: null });
    expect((steps[0] as { reply: string }).reply).toHaveLength(4000);
  });

  it("gives up after a fixed number of rounds", async () => {
    const endless = Array.from({ length: MAX_ROUNDS + 2 }, (_, i) => chatNeeded(`t${i}`));
    const { api } = fakeApi(endless);
    const failure = runTurn({ api, chat: replyWith("{}"), message: "m", token: null, dashboard: DASHBOARD, embedModel: null });
    await expect(failure).rejects.toMatchObject({ code: "too_many_steps" });
    expect(api.step).toHaveBeenCalledTimes(MAX_ROUNDS);
  });

  it("stops when aborted, without sending the reply", async () => {
    const { api } = fakeApi([chatNeeded("t1"), done("t2")]);
    const controller = new AbortController();
    const chat: AgentChat = vi.fn(async () => {
      controller.abort();
      return "{}";
    });
    const failure = runTurn({
      api,
      chat,
      message: "m",
      token: null,
      dashboard: DASHBOARD,
      embedModel: null,
      signal: controller.signal,
    });
    await expect(failure).rejects.toMatchObject({ name: "AbortError" });
    expect(api.step).not.toHaveBeenCalled();
  });

  it("passes the stop signal to the model", async () => {
    const { api } = fakeApi([chatNeeded("t1"), done("t2")]);
    const chat = vi.fn<AgentChat>().mockResolvedValue("{}");
    const controller = new AbortController();
    await runTurn({ api, chat, message: "m", token: null, dashboard: DASHBOARD, embedModel: null, signal: controller.signal });
    expect(chat.mock.calls[0][3]).toBe(controller.signal);
  });
});

// --- the HTTP client ---------------------------------------------------------------------

describe("httpAgentApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  // A new Response per call: a body can be read only once.
  function mockFetch(respond: () => Response) {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return respond();
      }),
    );
    vi.stubGlobal("document", { cookie: "csrftoken=abc" });
    return calls;
  }

  it("posts a turn and a step as JSON", async () => {
    const calls = mockFetch(() => new Response(JSON.stringify(done("t")), { status: 200 }));
    await httpAgentApi.turn({ message: "m", token: null, dashboard: DASHBOARD, embed: null });
    await httpAgentApi.step({ token: "t", reply: "{}" });
    expect(calls.map((c) => [c.url, c.init?.method])).toEqual([
      ["/api/ai/agent/turn/", "POST"],
      ["/api/ai/agent/step/", "POST"],
    ]);
    expect(JSON.parse(calls[1].init?.body as string)).toEqual({ token: "t", reply: "{}" });
  });

  it("turns a refusal into a problem with the server's code", async () => {
    mockFetch(() => new Response(JSON.stringify({ code: "token_expired", detail: "Start a new one." }), { status: 400 }));
    await expect(httpAgentApi.step({ token: "t", skip: true })).rejects.toBeInstanceOf(AgentProblem);
    await expect(httpAgentApi.step({ token: "t", skip: true })).rejects.toMatchObject({
      code: "token_expired",
      message: "Start a new one.",
    });
  });
});
