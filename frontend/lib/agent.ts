// The AI panel builder: the browser's half of the work. The server runs the workflow and keeps
// its state in a sealed token; it never calls a model. Whenever it needs one, it answers
// `needs_model` with the exact request to make, this browser makes it on the user's own Ollama,
// and sends the answer back as a step. Everything here takes its I/O as arguments (the server
// API, the chat stream, the embedder), so it is tested without a browser.

import { apiFetch } from "@/lib/api";
import { problemFrom, RagProblem, roundVector } from "@/lib/rag";
import type { AgentDashboard, AgentOutcome, AgentResponse, AgentStatus, ChatMessage } from "@/lib/types";

const BASE = "/api/ai/agent";
export const MAX_MESSAGE = 300; // the server's limit
const MAX_REPLY = 4000; // the server's limit on a relayed reply
// A turn needs at most a reply, two repairs and a merchant lookup; the server caps it too.
export const MAX_ROUNDS = 8;

// The server's {code, detail} refusals, as in "Ask".
export { RagProblem as AgentProblem };

export type TurnRequest = {
  message: string;
  token: string | null;
  dashboard: AgentDashboard;
  embed: { model: string; digest: string } | null; // the chosen embedding model, if any
};

export type StepAnswer = { reply: string } | { vector: number[] } | { skip: true };

export type AgentApi = {
  status(): Promise<AgentStatus>;
  turn(body: TurnRequest): Promise<AgentResponse>;
  step(body: { token: string } & StepAnswer): Promise<AgentResponse>;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw await problemFrom(res);
  return res.json();
}

export const httpAgentApi: AgentApi = {
  async status() {
    return json(await apiFetch(`${BASE}/status/`));
  },
  async turn(body) {
    return json(await apiFetch(`${BASE}/turn/`, { method: "POST", body: JSON.stringify(body) }));
  },
  async step(body) {
    return json(await apiFetch(`${BASE}/step/`, { method: "POST", body: JSON.stringify(body) }));
  },
};

// The model, as the dialog wires it: a chat that must answer in the given JSON shape...
export type AgentChat = (
  messages: ChatMessage[],
  options: Record<string, number>,
  format: object,
  signal?: AbortSignal,
) => Promise<string>;
// ...and an embedder for one text, when the user has an embedding model.
export type AgentEmbed = (model: string, text: string) => Promise<number[]>;

export type TurnResult = { token: string; outcome: AgentOutcome };

/**
 * One message end to end: send it, then answer every `needs_model` until the server is done.
 * A merchant lookup is skipped when there is no embedder; the server then just leaves the
 * merchant out with a note. A reply longer than the server accepts is cut, which the server
 * reads as a broken reply and asks the model to repair.
 */
export async function runTurn({
  api,
  chat,
  embed,
  message,
  token,
  dashboard,
  embedModel,
  onProgress,
  signal,
}: {
  api: AgentApi;
  chat: AgentChat;
  embed?: AgentEmbed;
  message: string;
  token: string | null;
  dashboard: AgentDashboard;
  embedModel: { model: string; digest: string } | null;
  onProgress?: (progress: { label: string; attempt: number }) => void;
  signal?: AbortSignal;
}): Promise<TurnResult> {
  let response = await api.turn({ message, token, dashboard, embed: embed ? embedModel : null });
  for (let round = 0; response.status === "needs_model"; round++) {
    if (round >= MAX_ROUNDS) {
      throw new RagProblem("too_many_steps", "This took too many tries. Try a simpler request.", 0);
    }
    signal?.throwIfAborted();
    onProgress?.(response.progress);
    const request = response.request;
    let answer: StepAnswer;
    if (request.kind === "chat") {
      const reply = await chat(request.messages, request.options, request.format, signal);
      answer = { reply: reply.slice(0, MAX_REPLY) };
    } else if (embed) {
      answer = { vector: roundVector(await embed(request.model, request.text)) };
    } else {
      answer = { skip: true };
    }
    signal?.throwIfAborted();
    response = await api.step({ token: response.token, ...answer });
  }
  return { token: response.token, outcome: response.outcome };
}
