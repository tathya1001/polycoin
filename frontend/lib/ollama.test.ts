import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_OLLAMA_URL, embed, listEmbeddingModels, loopbackUrl, OllamaError, savedOllamaUrl } from "./ollama";

const BASE = "http://localhost:11434";
const SECRET = "SECRET-NARRATION-9f3a"; // stands in for a real bank narration

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Replace fetch; `handler` gets the URL and the parsed JSON body (if any). */
function mockFetch(handler: (url: string, body: { model?: string; input?: string[] } | null) => Response) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return handler(url, init?.body ? JSON.parse(init.body as string) : null);
    }),
  );
  return calls;
}

async function failure(promise: Promise<unknown>): Promise<OllamaError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(OllamaError);
    return error as OllamaError;
  }
  throw new Error("expected an OllamaError");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- the address: this computer only -------------------------------------------

describe("loopbackUrl", () => {
  it.each([
    ["http://localhost:11434", "http://localhost:11434"],
    ["http://localhost:11434/", "http://localhost:11434"],
    ["  http://127.0.0.1:8080 ", "http://127.0.0.1:8080"],
    ["http://[::1]:11434", "http://[::1]:11434"],
    ["https://localhost", "https://localhost"],
  ])("accepts %s", (input, expected) => {
    expect(loopbackUrl(input)).toBe(expected);
  });

  it.each([
    "http://example.com:11434", // another machine: text would leave this computer
    "http://192.168.1.20:11434", // the local network is still another machine
    "http://localhost.example.com",
    "file:///etc/passwd",
    "http://user:pass@localhost:11434",
    "http://localhost:11434/api",
    "http://localhost:11434/?x=1",
    "localhost:11434",
    "",
  ])("rejects %s", (input) => {
    expect(loopbackUrl(input)).toBeNull();
  });
});

describe("savedOllamaUrl", () => {
  function storage(value: string | null) {
    vi.stubGlobal("localStorage", { getItem: () => value, setItem: () => {} });
  }

  it("defaults to Ollama's own port", () => {
    storage(null);
    expect(savedOllamaUrl()).toBe(DEFAULT_OLLAMA_URL);
  });

  it("uses a saved address on this computer", () => {
    storage("http://127.0.0.1:9999");
    expect(savedOllamaUrl()).toBe("http://127.0.0.1:9999");
  });

  it("ignores a saved address anywhere else", () => {
    storage("https://evil.example");
    expect(savedOllamaUrl()).toBe(DEFAULT_OLLAMA_URL);
  });

  it("still works when storage is unavailable", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(savedOllamaUrl()).toBe(DEFAULT_OLLAMA_URL);
  });
});

// --- listEmbeddingModels ----------------------------------------------------------

const TAGS = {
  models: [
    { name: "nomic-embed-text:latest", capabilities: ["embedding"], details: { embedding_length: 768 } },
    { name: "llama3.2:latest", capabilities: ["completion", "tools"], details: {} },
  ],
};

describe("listEmbeddingModels", () => {
  it("keeps only embedding models, asking this computer and sending no cookies", async () => {
    const calls = mockFetch(() => json(TAGS));

    expect(await listEmbeddingModels(BASE)).toEqual([{ name: "nomic-embed-text:latest", dimension: 768 }]);
    expect(calls[0].url).toBe(`${BASE}/api/tags`);
    expect(calls[0].init?.credentials).toBe("omit");
  });

  it("falls back to the name when an older Ollama lists no capabilities", async () => {
    mockFetch(() => json({ models: [{ name: "nomic-embed-text:latest" }, { name: "llama3:latest" }] }));

    expect(await listEmbeddingModels(BASE)).toEqual([{ name: "nomic-embed-text:latest", dimension: null }]);
  });

  it("says how to install a model when there is none", async () => {
    mockFetch(() => json({ models: [{ name: "llama3:latest", capabilities: ["completion"] }] }));

    const error = await failure(listEmbeddingModels(BASE));
    expect(error.code).toBe("no_embedding_models");
    expect(error.message).toContain("ollama pull nomic-embed-text");
  });

  it("treats a non-200 answer as unreachable", async () => {
    mockFetch(() => json({}, 500));

    expect((await failure(listEmbeddingModels(BASE))).code).toBe("unreachable");
  });

  it("treats a failed request as unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await failure(listEmbeddingModels(BASE));
    expect(error.code).toBe("unreachable");
    expect(error.message).toBe("Can't reach Ollama on this computer.");
  });

  it("says when Ollama is too slow", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("timed out", "TimeoutError")));

    expect((await failure(listEmbeddingModels(BASE))).message).toBe("Ollama took too long to answer.");
  });
});

// --- embed -------------------------------------------------------------------------

describe("embed", () => {
  const echo = (_url: string, body: { input?: string[] } | null) =>
    json({ embeddings: (body?.input ?? []).map((text) => [text.length, 1]) });

  it("sends batches of 64 in order and reports progress", async () => {
    const calls = mockFetch(echo);
    const texts = Array.from({ length: 130 }, (_, i) => "x".repeat(i + 1));
    const progress: number[] = [];

    const vectors = await embed(BASE, "nomic-embed-text", texts, (done) => progress.push(done));

    expect(calls.map((c) => JSON.parse(c.init?.body as string).input.length)).toEqual([64, 64, 2]);
    expect(calls.every((c) => c.url === `${BASE}/api/embed` && c.init?.method === "POST")).toBe(true);
    expect(JSON.parse(calls[0].init?.body as string).model).toBe("nomic-embed-text");
    expect(vectors.map((v) => v[0])).toEqual(texts.map((t) => t.length));
    expect(progress).toEqual([64, 128, 130]);
  });

  it("makes no request for nothing", async () => {
    const calls = mockFetch(echo);

    expect(await embed(BASE, "m", [])).toEqual([]);
    expect(calls).toHaveLength(0);
  });

  it.each([
    [404, "model_not_found"],
    [500, "embedding_failed"],
  ])("maps HTTP %i to %s", async (status, code) => {
    mockFetch(() => json({ error: "nope" }, status));

    expect((await failure(embed(BASE, "m", [SECRET]))).code).toBe(code);
  });

  it("rejects the wrong number of vectors", async () => {
    mockFetch(() => json({ embeddings: [] }));

    expect((await failure(embed(BASE, "m", [SECRET]))).code).toBe("embedding_failed");
  });

  it("rejects vectors of different sizes across batches", async () => {
    let call = 0;
    mockFetch((_url, body) => json({ embeddings: (body?.input ?? []).map(() => (call++ < 64 ? [1, 2] : [1, 2, 3])) }));

    const texts = Array.from({ length: 65 }, (_, i) => `t${i}`);
    expect((await failure(embed(BASE, "m", texts))).code).toBe("dimension_mismatch");
  });

  it("never puts transaction text in an error", async () => {
    for (const status of [404, 500]) {
      mockFetch(() => json({}, status));
      expect((await failure(embed(BASE, "m", [SECRET]))).message).not.toContain(SECRET);
    }
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError(SECRET)));
    expect((await failure(embed(BASE, "m", [SECRET]))).message).not.toContain(SECRET);
  });
});
