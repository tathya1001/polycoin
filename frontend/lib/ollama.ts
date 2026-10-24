// The user's own Ollama, called straight from this browser. Transaction text goes from here to
// the user's computer and nowhere else; our server never talks to Ollama. Only addresses on this
// computer are accepted, so that promise can't be broken by a typo or a crafted setting.

import type { ChatMessage, ChatModel, EmbeddingModel } from "@/lib/types";
import { recall, remember } from "@/lib/storage";

export const DEFAULT_OLLAMA_URL = "http://localhost:11434";
const URL_KEY = "polycoin.ai.ollamaUrl";
const BATCH_SIZE = 64;
const TIMEOUT_MS = 60_000; // per request; a big batch on a slow machine can take a while
// A streamed answer may run for minutes on a CPU, so chat has no total timeout: it fails only when
// Ollama goes quiet. The first token waits longest, because Ollama may still be loading the model.
const FIRST_TOKEN_MS = 180_000;
const IDLE_MS = 60_000;

export type OllamaErrorCode =
  | "unreachable"
  | "no_embedding_models"
  | "model_not_found"
  | "embedding_failed"
  | "dimension_mismatch"
  | "no_chat_models"
  | "chat_failed";

export class OllamaError extends Error {
  code: OllamaErrorCode;

  constructor(code: OllamaErrorCode, message: string) {
    super(message);
    this.name = "OllamaError";
    this.code = code;
  }
}

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** `input` as a base URL ("http://localhost:11434"), or null unless it points at this computer. */
export function loopbackUrl(input: string): string | null {
  try {
    const url = new URL(input.trim());
    if ((url.protocol !== "http:" && url.protocol !== "https:") || !LOOPBACK.has(url.hostname)) return null;
    if (url.username || url.password || url.search || url.hash || url.pathname !== "/") return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function savedOllamaUrl(): string {
  return loopbackUrl(recall(URL_KEY) ?? "") ?? DEFAULT_OLLAMA_URL;
}

export function saveOllamaUrl(url: string) {
  remember(URL_KEY, url);
}

async function call(base: string, path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(base + path, {
      ...init,
      credentials: "omit", // Ollama needs no cookies, and gets none of ours
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    // The browser hides why a request failed: Ollama not running, this site's origin not in
    // OLLAMA_ORIGINS, and a blocked local-network request all look the same here.
    const slow = error instanceof DOMException && error.name === "TimeoutError";
    throw new OllamaError("unreachable", slow ? "Ollama took too long to answer." : "Can't reach Ollama on this computer.");
  }
}

type Tag = { name: string; digest?: string; capabilities?: string[]; details?: { embedding_length?: number } };

async function listTags(base: string): Promise<Tag[]> {
  const res = await call(base, "/api/tags");
  if (!res.ok) throw new OllamaError("unreachable", "Ollama answered, but not with a model list.");
  const body: { models?: Tag[] } = await res.json();
  return body.models ?? [];
}

// Older Ollama versions don't report capabilities; then the name is the only hint.
function isEmbedding(tag: Tag): boolean {
  return tag.capabilities ? tag.capabilities.includes("embedding") : tag.name.toLowerCase().includes("embed");
}

/** Installed models that can produce embeddings. */
export async function listEmbeddingModels(base: string): Promise<EmbeddingModel[]> {
  const models = (await listTags(base))
    .filter(isEmbedding)
    .map((m) => ({ name: m.name, dimension: m.details?.embedding_length ?? null, digest: m.digest }));

  if (models.length === 0) {
    throw new OllamaError("no_embedding_models", "Ollama has no embedding model installed. Run: ollama pull nomic-embed-text");
  }
  return models;
}

/** One vector per text, in order, all the same size. `onProgress` gets the count done so far. */
export async function embed(
  base: string,
  model: string,
  texts: string[],
  onProgress?: (done: number) => void,
): Promise<number[][]> {
  const vectors: number[][] = [];
  for (let start = 0; start < texts.length; start += BATCH_SIZE) {
    const batch = texts.slice(start, start + BATCH_SIZE);
    const res = await call(base, "/api/embed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, input: batch }),
    });

    if (res.status === 404) throw new OllamaError("model_not_found", `Model '${model}' isn't installed in Ollama.`);
    if (!res.ok) throw new OllamaError("embedding_failed", `Ollama failed to embed a batch (HTTP ${res.status}).`);

    const returned: number[][] = (await res.json()).embeddings ?? [];
    if (returned.length !== batch.length) {
      throw new OllamaError("embedding_failed", "Ollama returned the wrong number of vectors.");
    }
    vectors.push(...returned);
    if (new Set(vectors.map((v) => v.length)).size > 1) {
      throw new OllamaError("dimension_mismatch", "Ollama returned vectors of different sizes.");
    }
    onProgress?.(vectors.length);
  }
  return vectors;
}

/** Installed models that can chat (write answers), not embedding-only ones. */
export async function listChatModels(base: string): Promise<ChatModel[]> {
  const models = (await listTags(base))
    .filter((m) => (m.capabilities ? m.capabilities.includes("completion") : !isEmbedding(m)))
    .map((m) => ({ name: m.name }));
  if (models.length === 0) {
    throw new OllamaError("no_chat_models", "Ollama has no chat model installed. Run: ollama pull llama3.2");
  }
  return models;
}

/**
 * Streams one chat answer from /api/chat, calling `onToken` with each piece as it arrives, and
 * resolves with the whole text. Ollama sends one JSON object per line (NDJSON); a line can be
 * split across network chunks, so text is buffered until its newline arrives.
 *
 * `signal` cancels (the user pressed Stop): the promise then rejects with the abort's
 * DOMException, which callers treat as "stopped", not as a failure.
 *
 * `extra.format` is a JSON schema: Ollama then constrains the answer to JSON of that shape
 * (structured outputs), still streamed.
 */
export async function chatStream(
  base: string,
  model: string,
  messages: ChatMessage[],
  options: Record<string, number>,
  onToken: (text: string) => void,
  signal?: AbortSignal,
  extra?: { format?: object },
): Promise<string> {
  const quiet = new AbortController();
  let timer = setTimeout(() => quiet.abort(), FIRST_TOKEN_MS);
  const stop = signal ? AbortSignal.any([signal, quiet.signal]) : quiet.signal;

  try {
    let res: Response;
    try {
      res = await fetch(`${base}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages, options, stream: true, ...(extra?.format && { format: extra.format }) }),
        credentials: "omit",
        cache: "no-store",
        signal: stop,
      });
    } catch (error) {
      throw stopped(error, signal, quiet.signal);
    }
    if (res.status === 404) throw new OllamaError("model_not_found", `Model '${model}' isn't installed in Ollama.`);
    if (!res.ok || !res.body) throw new OllamaError("chat_failed", `Ollama couldn't answer (HTTP ${res.status}).`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    let answer = "";
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (error) {
        throw stopped(error, signal, quiet.signal);
      }
      clearTimeout(timer);
      timer = setTimeout(() => quiet.abort(), IDLE_MS);
      buffered += decoder.decode(chunk.value, { stream: !chunk.done });

      const lines = buffered.split("\n");
      buffered = chunk.done ? "" : (lines.pop() ?? "");
      for (const line of lines) {
        if (!line.trim()) continue;
        const event: { message?: { content?: string }; done?: boolean; error?: string } = JSON.parse(line);
        if (event.error) throw new OllamaError("chat_failed", `Ollama couldn't answer: ${event.error}`);
        const piece = event.message?.content ?? "";
        if (piece) {
          answer += piece;
          onToken(piece);
        }
        if (event.done) return answer;
      }
      if (chunk.done) return answer;
    }
  } finally {
    clearTimeout(timer);
  }
}

// The user's Stop stays an abort; Ollama going quiet becomes an "unreachable" OllamaError.
function stopped(error: unknown, user: AbortSignal | undefined, quiet: AbortSignal): unknown {
  if (user?.aborted) return error;
  if (quiet.aborted) return new OllamaError("unreachable", "Ollama stopped answering.");
  return new OllamaError("unreachable", "Can't reach Ollama on this computer.");
}
