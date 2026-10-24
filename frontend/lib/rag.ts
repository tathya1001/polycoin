// "Ask your transactions": the browser's half of the work. The server stores the encrypted index,
// searches it and builds the prompt; only this browser can reach the user's own Ollama, so it
// embeds the texts and the question and streams the answer. Everything here takes its I/O as
// arguments (the server API, the embedder, the chat stream), so it is tested without a browser.

import { apiFetch } from "@/lib/api";
import type {
  AskFilters,
  AskResponse,
  ChatMessage,
  PendingBatch,
  RagSource,
  RagStatus,
  StoreResult,
  VectorItem,
} from "@/lib/types";

const BASE = "/api/ai/rag";
const MAX_BATCH = 100; // the server's RAG_INDEX_BATCH
// Numbers per upload, to stay well under Django's 2.5 MB request limit: about 9 bytes of JSON
// each once rounded, so 100 x 768 is about 0.7 MB, and a 4096-dimension model gets 24 rows.
const MAX_NUMBERS_PER_UPLOAD = 100_000;
const DECIMALS = 1e5; // the index stores float16, so more digits only cost bandwidth

/** A refusal from the RAG endpoints: the server's machine-readable `code` and its message. */
export class RagProblem extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "RagProblem";
    this.code = code;
    this.status = status;
  }
}

/** The server's {code, detail} refusal as an error; the panel builder's client uses it too. */
export async function problemFrom(res: Response): Promise<RagProblem> {
  try {
    const body = await res.json();
    if (typeof body?.code === "string" && typeof body?.detail === "string") {
      return new RagProblem(body.code, body.detail, res.status);
    }
    if (typeof body?.detail === "string") return new RagProblem("error", body.detail, res.status);
  } catch {
    // not JSON: fall through
  }
  return new RagProblem("error", `The server refused the request (HTTP ${res.status}).`, res.status);
}

// --- the server API --------------------------------------------------------------------------

export type RagApi = {
  status(model: string, digest: string): Promise<RagStatus>;
  pending(model: string, digest: string, limit: number): Promise<PendingBatch>;
  store(model: string, digest: string, items: VectorItem[]): Promise<StoreResult>;
  ask(body: AskRequest): Promise<AskResponse>;
  clear(): Promise<void>;
};

export type AskRequest = {
  model: string;
  digest: string;
  question: string;
  vector: number[];
  filters: AskFilters;
  use_question_period: boolean;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw await problemFrom(res);
  return res.json();
}

function modelQuery(model: string, digest: string): string {
  return new URLSearchParams({ model, digest }).toString();
}

export const httpRagApi: RagApi = {
  async status(model, digest) {
    return json(await apiFetch(`${BASE}/status/?${modelQuery(model, digest)}`));
  },
  async pending(model, digest, limit) {
    return json(await apiFetch(`${BASE}/pending/?${modelQuery(model, digest)}&limit=${limit}`));
  },
  async store(model, digest, items) {
    const body = JSON.stringify({ model, digest, items });
    return json(await apiFetch(`${BASE}/vectors/`, { method: "POST", body }));
  },
  async ask(body) {
    return json(await apiFetch(`${BASE}/ask/`, { method: "POST", body: JSON.stringify(body) }));
  },
  async clear() {
    const res = await apiFetch(`${BASE}/index/`, { method: "DELETE" });
    if (!res.ok) throw await problemFrom(res);
  },
};

// --- indexing --------------------------------------------------------------------------------

export type Embedder = (texts: string[]) => Promise<number[][]>;

/** Rows per round trip for vectors of `dims` numbers (unknown: assume a large model). */
export function batchSize(dims: number | null): number {
  return Math.max(1, Math.min(MAX_BATCH, Math.floor(MAX_NUMBERS_PER_UPLOAD / (dims ?? 4096))));
}

export function roundVector(vector: number[]): number[] {
  return vector.map((value) => Math.round(value * DECIMALS) / DECIMALS);
}

export type SyncProgress = { stored: number; remaining: number };

/**
 * Embeds every row the server says is missing or stale, batch by batch, until nothing remains.
 * Rows edited mid-batch come back as stale and are picked up by the next batch. It stops early
 * if a batch stores nothing, so rows the server keeps rejecting can't loop forever.
 */
export async function syncIndex({
  api,
  embed,
  model,
  digest,
  dims,
  onProgress,
  signal,
}: {
  api: RagApi;
  embed: Embedder;
  model: string;
  digest: string;
  dims: number | null;
  onProgress?: (progress: SyncProgress) => void;
  signal?: AbortSignal;
}): Promise<SyncProgress> {
  let stored = 0;
  let size = batchSize(dims);
  for (;;) {
    signal?.throwIfAborted();
    const batch = await api.pending(model, digest, size);
    if (batch.items.length === 0) return { stored, remaining: batch.remaining };

    const vectors = await embed(batch.items.map((item) => item.text));
    signal?.throwIfAborted();
    size = batchSize(vectors[0]?.length ?? dims); // now the real size is known
    const items = batch.items.map((item, i) => ({
      transaction: item.transaction,
      version: item.version,
      vector: roundVector(vectors[i]),
    }));
    const result = await api.store(model, digest, items);
    stored += result.stored;
    const remaining = batch.remaining + result.stale + result.rejected;
    onProgress?.({ stored, remaining });
    if (result.stored === 0 && result.stale === 0) return { stored, remaining };
  }
}

// --- asking ----------------------------------------------------------------------------------

export type ChatStreamer = (
  messages: ChatMessage[],
  options: Record<string, number>,
  onToken: (text: string) => void,
  signal?: AbortSignal,
) => Promise<string>;

/**
 * One question end to end: embed it (with the model's query prefix), let the server search and
 * build the prompt, then stream the answer from the user's Ollama. With no matches the server
 * returns no messages, and the model is not called at all.
 */
export async function ask({
  api,
  embed,
  chat,
  model,
  digest,
  queryPrefix,
  question,
  filters,
  useQuestionPeriod,
  onResponse,
  onToken,
  signal,
}: {
  api: RagApi;
  embed: Embedder;
  chat: ChatStreamer;
  model: string;
  digest: string;
  queryPrefix: string;
  question: string;
  filters: AskFilters;
  useQuestionPeriod: boolean;
  onResponse?: (response: AskResponse) => void; // the sources show before the answer streams
  onToken?: (text: string) => void;
  signal?: AbortSignal;
}): Promise<{ response: AskResponse; answer: string | null }> {
  const [vector] = await embed([queryPrefix + question]);
  signal?.throwIfAborted();
  const response = await api.ask({
    model,
    digest,
    question,
    vector: roundVector(vector),
    filters,
    use_question_period: useQuestionPeriod,
  });
  onResponse?.(response);
  if (!response.messages) return { response, answer: null };
  const answer = await chat(response.messages, response.options, (text) => onToken?.(text), signal);
  return { response, answer };
}

// --- citations -------------------------------------------------------------------------------

export type AnswerSegment = { kind: "text"; text: string } | { kind: "cite"; source: RagSource };

// "[3]", or a list such as "[1, 4]" that some models write.
const CITATION = /\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/g;

/**
 * Splits a model's answer into plain text and citations, for rendering as text nodes only (the
 * answer is untrusted: never HTML, never markdown, never a link built from its words).
 *
 * A citation counts only if it names a source the prompt held (1..inPrompt) and that source is in
 * the response; anything else is dropped, so a made-up "[17]" never links to a row.
 */
export function parseCitations(answer: string, sources: RagSource[], inPrompt: number): AnswerSegment[] {
  const byNumber = new Map(sources.filter((s) => s.n <= inPrompt).map((s) => [s.n, s]));
  const segments: AnswerSegment[] = [];
  let last = 0;
  const pushText = (text: string) => {
    if (!text) return;
    const previous = segments.at(-1);
    if (previous?.kind === "text") previous.text += text;
    else segments.push({ kind: "text", text });
  };

  for (const match of answer.matchAll(CITATION)) {
    pushText(answer.slice(last, match.index));
    for (const number of match[1].split(",")) {
      const source = byNumber.get(Number(number.trim()));
      if (source) segments.push({ kind: "cite", source });
    }
    last = match.index + match[0].length;
  }
  pushText(answer.slice(last));
  return segments;
}
