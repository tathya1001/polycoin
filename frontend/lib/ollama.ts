// The user's own Ollama, called straight from this browser. Transaction text goes from here to
// the user's computer and nowhere else; our server never talks to Ollama. Only addresses on this
// computer are accepted, so that promise can't be broken by a typo or a crafted setting.

import type { EmbeddingModel } from "@/lib/types";
import { recall, remember } from "@/lib/storage";

export const DEFAULT_OLLAMA_URL = "http://localhost:11434";
const URL_KEY = "polycoin.ai.ollamaUrl";
const BATCH_SIZE = 64;
const TIMEOUT_MS = 60_000; // per request, like the server's old OLLAMA_TIMEOUT

export type OllamaErrorCode =
  | "unreachable"
  | "no_embedding_models"
  | "model_not_found"
  | "embedding_failed"
  | "dimension_mismatch";

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

type Tag = { name: string; capabilities?: string[]; details?: { embedding_length?: number } };

/** Installed models that can produce embeddings. */
export async function listEmbeddingModels(base: string): Promise<EmbeddingModel[]> {
  const res = await call(base, "/api/tags");
  if (!res.ok) throw new OllamaError("unreachable", "Ollama answered, but not with a model list.");

  const body: { models?: Tag[] } = await res.json();
  const models = (body.models ?? [])
    .filter((m) => (m.capabilities ? m.capabilities.includes("embedding") : m.name.toLowerCase().includes("embed")))
    .map((m) => ({ name: m.name, dimension: m.details?.embedding_length ?? null }));

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
