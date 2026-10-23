import { describe, expect, it, vi } from "vitest";
import {
  ask,
  batchSize,
  parseCitations,
  roundVector,
  syncIndex,
  type AnswerSegment,
  type RagApi,
} from "./rag";
import type { AskResponse, PendingItem, RagSource } from "./types";

function source(n: number): RagSource {
  return {
    n,
    transaction: `t${n}`,
    date: "2026-01-05",
    txn_type: "debit",
    amount: "1500.00",
    name: `Row ${n}`,
    category: { id: "c", name: "Health", color: "#2A78D6" },
  };
}

const SOURCES = [1, 2, 3].map(source);

function text(segments: AnswerSegment[]): string {
  return segments.map((s) => (s.kind === "text" ? s.text : `{${s.source.n}}`)).join("");
}

// --- parseCitations: the answer is untrusted text ----------------------------------

describe("parseCitations", () => {
  it("turns [n] into citations of the matching rows and keeps the rest as text", () => {
    const segments = parseCitations("You paid the gym [1]. Again in March [3].", SOURCES, 3);
    expect(text(segments)).toBe("You paid the gym {1}. Again in March {3}.");
    expect(segments.filter((s) => s.kind === "cite").map((s) => s.kind === "cite" && s.source.transaction)).toEqual([
      "t1",
      "t3",
    ]);
  });

  it("reads lists like [1, 2] that some models write", () => {
    expect(text(parseCitations("Both [1, 2].", SOURCES, 3))).toBe("Both {1}{2}.");
  });

  it("drops references to rows that don't exist, so a made-up [17] never links anywhere", () => {
    expect(text(parseCitations("See [17] and [0] and [2].", SOURCES, 3))).toBe("See  and  and {2}.");
  });

  it("drops references the prompt never held, even when the row is in the list", () => {
    expect(text(parseCitations("[1] [3]", SOURCES, 2))).toBe("{1} ");
  });

  it("keeps HTML, script and markdown as literal text", () => {
    const hostile = '<script>alert(1)</script> **bold** [click](https://evil.example) <img src=x onerror=alert(1)>';
    const segments = parseCitations(hostile, SOURCES, 3);
    expect(segments).toEqual([{ kind: "text", text: hostile }]);
  });

  it("returns nothing for an empty answer and plain text for one with no citations", () => {
    expect(parseCitations("", SOURCES, 3)).toEqual([]);
    expect(parseCitations("Nothing found.", SOURCES, 3)).toEqual([{ kind: "text", text: "Nothing found." }]);
  });

  it("leaves a half-streamed citation as text until it closes", () => {
    expect(text(parseCitations("So far [", SOURCES, 3))).toBe("So far [");
    expect(text(parseCitations("So far [1", SOURCES, 3))).toBe("So far [1");
  });
});

// --- batching ------------------------------------------------------------------------

describe("batchSize", () => {
  it.each([
    [768, 100], // nomic: the server's full batch
    [1024, 97],
    [4096, 24], // a large model stays under Django's request limit
    [null, 24], // unknown: assume large until the first vectors arrive
  ])("%s dimensions -> %i rows", (dims, rows) => {
    expect(batchSize(dims)).toBe(rows);
  });

  it("never drops below one row", () => {
    expect(batchSize(1_000_000)).toBe(1);
  });
});

it("rounds vectors to five decimals", () => {
  expect(roundVector([0.123456789, -0.000004, 1])).toEqual([0.12346, -0, 1]);
});

// --- syncIndex -----------------------------------------------------------------------

function pendingItems(count: number, start = 0): PendingItem[] {
  return Array.from({ length: count }, (_, i) => ({
    transaction: `t${start + i}`,
    version: "v",
    text: `search_document: text ${start + i}`,
  }));
}

function fakeApi(total: number) {
  let left = total;
  const stored: string[] = [];
  const api: RagApi = {
    status: vi.fn(),
    async pending(_model, _digest, limit) {
      const items = pendingItems(Math.min(limit, left), total - left);
      return { items, remaining: left - items.length };
    },
    async store(_model, _digest, items) {
      stored.push(...items.map((item) => item.transaction));
      left -= items.length;
      return { stored: items.length, stale: 0, rejected: 0 };
    },
    ask: vi.fn(),
    clear: vi.fn(),
  };
  return { api, stored };
}

const embed768 = async (texts: string[]) => texts.map(() => Array(768).fill(0.123456));

describe("syncIndex", () => {
  it("embeds batch by batch until nothing remains, reporting progress", async () => {
    const { api, stored } = fakeApi(250);
    const progress: { stored: number; remaining: number }[] = [];

    const result = await syncIndex({
      api,
      embed: embed768,
      model: "nomic-embed-text:latest",
      digest: "sha256:abc",
      dims: 768,
      onProgress: (p) => progress.push(p),
    });

    expect(result).toEqual({ stored: 250, remaining: 0 });
    expect(stored).toHaveLength(250);
    expect(progress.map((p) => p.stored)).toEqual([100, 200, 250]);
  });

  it("sends the text exactly as the server gave it (with its prefix) and rounded vectors", async () => {
    const { api } = fakeApi(1);
    const embed = vi.fn(embed768);
    const store = vi.spyOn(api, "store");

    await syncIndex({ api, embed, model: "m", digest: "d", dims: 768 });

    expect(embed).toHaveBeenCalledWith(["search_document: text 0"]);
    expect(store.mock.calls[0][2][0]).toMatchObject({ transaction: "t0", version: "v" });
    expect(store.mock.calls[0][2][0].vector[0]).toBe(0.12346);
  });

  it("starts small when the size is unknown, then uses the real size", async () => {
    const { api } = fakeApi(130);
    const pending = vi.spyOn(api, "pending");

    await syncIndex({ api, embed: embed768, model: "m", digest: "d", dims: null });

    expect(pending.mock.calls.map((call) => call[2])).toEqual([24, 100, 100, 100]); // the last finds nothing
  });

  it("stops when a batch stores nothing, so rejected rows can't loop forever", async () => {
    const { api } = fakeApi(10);
    api.store = async (_model, _digest, items) => ({ stored: 0, stale: 0, rejected: items.length });

    const result = await syncIndex({ api, embed: embed768, model: "m", digest: "d", dims: 768 });
    expect(result).toEqual({ stored: 0, remaining: 10 });
  });

  it("stops when cancelled", async () => {
    const { api } = fakeApi(500);
    const controller = new AbortController();
    const embed = async (texts: string[]) => {
      controller.abort();
      return embed768(texts);
    };

    await expect(
      syncIndex({ api, embed, model: "m", digest: "d", dims: 768, signal: controller.signal }),
    ).rejects.toThrow();
  });
});

// --- ask -----------------------------------------------------------------------------

function response(messages: AskResponse["messages"]): AskResponse {
  return {
    prompt_version: "rag-v2",
    profile: { doc_prefix: "search_document: ", query_prefix: "search_query: ", tuned: true },
    period: { from: "2025-11-01", to: "2026-10-15", source: "filter", phrase: null },
    coverage: { searched: 3, indexed: 3, total: 3 },
    summary: { matches: 3, debit_total: "4500.00", credit_total: "0.00", first_date: null, last_date: null },
    sources: SOURCES,
    in_prompt: 3,
    messages,
    options: { temperature: 0.1, num_ctx: 4096 },
  };
}

describe("ask", () => {
  const filters = { date: { preset: "all" as const }, type: null };

  it("embeds the question with the query prefix, then streams the server's prompt", async () => {
    const messages = [{ role: "user" as const, content: "prompt" }];
    const api = { ...fakeApi(0).api, ask: vi.fn(async () => response(messages)) };
    const embed = vi.fn(async () => [[0.1234567, 0.5]]);
    const chat = vi.fn(async (_messages: unknown, _options: unknown, onToken: (t: string) => void) => {
      onToken("You paid ");
      onToken("[1].");
      return "You paid [1].";
    });
    const tokens: string[] = [];

    const result = await ask({
      api,
      embed,
      chat,
      model: "m",
      digest: "d",
      queryPrefix: "search_query: ",
      question: "gym?",
      filters,
      useQuestionPeriod: true,
      onToken: (t) => tokens.push(t),
    });

    expect(embed).toHaveBeenCalledWith(["search_query: gym?"]);
    expect(api.ask).toHaveBeenCalledWith({
      model: "m",
      digest: "d",
      question: "gym?", // the server gets the question without the prefix
      vector: [0.12346, 0.5],
      filters,
      use_question_period: true,
    });
    expect(chat.mock.calls[0][0]).toEqual(messages);
    expect(chat.mock.calls[0][1]).toEqual({ temperature: 0.1, num_ctx: 4096 });
    expect(tokens.join("")).toBe("You paid [1].");
    expect(result.answer).toBe("You paid [1].");
  });

  it("never calls the model when nothing matched", async () => {
    const api = { ...fakeApi(0).api, ask: vi.fn(async () => response(null)) };
    const chat = vi.fn();

    const result = await ask({
      api,
      embed: async () => [[1, 0]],
      chat,
      model: "m",
      digest: "d",
      queryPrefix: "",
      question: "horse riding",
      filters,
      useQuestionPeriod: true,
    });

    expect(chat).not.toHaveBeenCalled();
    expect(result.answer).toBeNull();
  });
});
