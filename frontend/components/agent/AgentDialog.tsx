"use client";

// The AI panel builder: the user describes a chart, the user's own Ollama and the server build
// one panel, and follow-up messages change that same panel.
//
// Flow (lib/agent.ts): POST /api/ai/agent/turn/ -> while the server needs the model, this
// browser asks the user's Ollama and POSTs the answer to step/ -> a preview, a "not a panel",
// or a failure. The server never calls a model and stores nothing: the conversation lives in a
// sealed token, and the token, the messages and the preview live in this component's state only.

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { CircleStop, Pencil, Plus, Sparkles } from "lucide-react";
import { OllamaSetup } from "@/components/ai/OllamaSetup";
import AgentPreview, { MAX_TITLE } from "@/components/agent/AgentPreview";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorNote, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Select } from "@/components/ui/Field";
import { AgentProblem, httpAgentApi, MAX_MESSAGE, runTurn } from "@/lib/agent";
import { categoryColorMap } from "@/lib/insights";
import { chatStream, embed, listChatModels, listEmbeddingModels, OllamaError, savedOllamaUrl, saveOllamaUrl } from "@/lib/ollama";
import { recall, remember } from "@/lib/storage";
import type { AgentDashboard, AgentOutcome, Category, ChatModel, EmbeddingModel, PanelConfig } from "@/lib/types";

const EMBED_MODEL_KEY = "polycoin.ai.model"; // shared with Ask and Categorize
const CHAT_MODEL_KEY = "polycoin.ai.chatModel"; // shared with Ask
const NO_EMBEDDER = "";

type Preview = Extract<AgentOutcome, { kind: "preview" }>;
type LogEntry = { from: "you" | "ai"; text: string };

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

// Older Ollama versions report no digest; the name alone then identifies the index, as in Ask.
function digestOf(model: EmbeddingModel): string {
  return model.digest ?? "unknown";
}

function pickSaved<T extends { name: string }>(models: T[], key: string, fallback: string): string {
  const saved = recall(key);
  return models.find((m) => m.name === saved)?.name ?? fallback;
}

// Conversation problems that a new conversation fixes: the next message starts one.
const RESTART = new Set(["token_expired", "token_invalid", "too_many_turns", "state_too_large"]);

function explain(problem: unknown): string {
  if (problem instanceof OllamaError) {
    return problem.code === "unreachable" ? `${problem.message} Is it still running?` : problem.message;
  }
  if (problem instanceof AgentProblem) {
    if (problem.code === "agent_disabled") return "The AI panel builder is turned off for now.";
    if (RESTART.has(problem.code)) return `${problem.message} Your next message starts a new conversation.`;
    return problem.message;
  }
  if (problem instanceof TypeError) return "Cannot reach the server.";
  return "Something went wrong. Please try again.";
}

export default function AgentDialog({
  dashboard,
  categories,
  canAdd,
  onClose,
  onAdd,
  onEditFirst,
}: {
  dashboard: AgentDashboard;
  categories: Category[];
  canAdd: boolean; // false when the dashboard already has its maximum of panels
  onClose: () => void;
  onAdd: (title: string, config: PanelConfig) => Promise<string | null>; // an error, or null
  onEditFirst: (title: string, config: PanelConfig) => void;
}) {
  // The user's Ollama and the chosen models.
  const [ollamaUrl, setOllamaUrl] = useState(savedOllamaUrl);
  const [chatModels, setChatModels] = useState<ChatModel[]>([]);
  const [embedModels, setEmbedModels] = useState<EmbeddingModel[]>([]);
  const [chatName, setChatName] = useState("");
  const [embedName, setEmbedName] = useState(NO_EMBEDDER);
  const [ollamaProblem, setOllamaProblem] = useState<OllamaError | null>(null);
  const [checking, setChecking] = useState(true);
  const [attempt, setAttempt] = useState(0); // bumped by "Check again"
  const [enabled, setEnabled] = useState<boolean | null>(null);

  // The conversation.
  const [message, setMessage] = useState("");
  const [log, setLog] = useState<LogEntry[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [failedConfig, setFailedConfig] = useState<{ title: string; config: PanelConfig } | null>(null);
  const [notPanel, setNotPanel] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const categoryColors = useMemo(() => categoryColorMap(categories), [categories]);
  const embedModel = embedModels.find((m) => m.name === embedName) ?? null;

  useEffect(() => {
    let cancelled = false;
    httpAgentApi
      .status()
      .then((status) => !cancelled && setEnabled(status.enabled))
      .catch((problem) => !cancelled && setError(explain(problem))); // the form stays disabled
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Straight from this browser to the user's own Ollama; our server is not involved.
    (async () => {
      try {
        const chat = await listChatModels(ollamaUrl);
        // An embedding model is optional: it only helps find a merchant by meaning.
        const embedding = await listEmbeddingModels(ollamaUrl).catch(() => [] as EmbeddingModel[]);
        if (cancelled) return;
        setOllamaProblem(null);
        setChatModels(chat);
        setEmbedModels(embedding);
        setChatName(pickSaved(chat, CHAT_MODEL_KEY, chat[0]?.name ?? ""));
        setEmbedName(pickSaved(embedding, EMBED_MODEL_KEY, NO_EMBEDDER));
      } catch (problem) {
        if (cancelled) return;
        setOllamaProblem(
          problem instanceof OllamaError ? problem : new OllamaError("unreachable", "Can't reach Ollama on this computer."),
        );
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ollamaUrl, attempt]);

  useEffect(() => () => abort.current?.abort(), []);

  function checkAgain() {
    setChecking(true);
    setAttempt((n) => n + 1);
  }

  function changeOllamaUrl(url: string) {
    saveOllamaUrl(url);
    setOllamaUrl(url);
    checkAgain();
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = message.trim();
    if (!text || !chatName || running) return;
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    setError(null);
    setNotPanel(null);
    setProgress("Sending");
    setLog((entries) => [...entries, { from: "you", text }]);
    setMessage("");
    try {
      const result = await runTurn({
        api: httpAgentApi,
        chat: (messages, options, format, signal) =>
          chatStream(ollamaUrl, chatName, messages, options, () => {}, signal, { format }),
        embed: embedModel ? async (model, phrase) => (await embed(ollamaUrl, model, [phrase]))[0] : undefined,
        message: text,
        token,
        dashboard,
        embedModel: embedModel ? { model: embedModel.name, digest: digestOf(embedModel) } : null,
        onProgress: (step) => setProgress(step.attempt > 1 ? `${step.label} (try ${step.attempt})` : step.label),
        signal: controller.signal,
      });
      setToken(result.token);
      const outcome = result.outcome;
      if (outcome.kind === "preview") {
        setPreview(outcome);
        setFailedConfig(null);
        setTitle(outcome.title.slice(0, MAX_TITLE));
        setLog((entries) => [...entries, { from: "ai", text: outcome.summary }]);
      } else if (outcome.kind === "not_a_panel") {
        setNotPanel(outcome.reason);
        setLog((entries) => [...entries, { from: "ai", text: outcome.reason }]);
      } else {
        setFailedConfig(outcome.config ? { title: outcome.title ?? "", config: outcome.config } : null);
        setLog((entries) => [...entries, { from: "ai", text: outcome.detail }]);
      }
    } catch (problem) {
      if (isAbort(problem)) {
        setLog((entries) => [...entries, { from: "ai", text: "Stopped." }]);
      } else {
        setMessage((current) => current || text); // give the words back to send again
        if (problem instanceof AgentProblem && RESTART.has(problem.code)) setToken(null);
        if (problem instanceof OllamaError && problem.code === "unreachable") setOllamaProblem(problem);
        setError(explain(problem));
      }
    } finally {
      if (abort.current === controller) abort.current = null;
      setRunning(false);
      setProgress(null);
    }
  }

  async function add() {
    if (!preview) return;
    setAdding(true);
    const problem = await onAdd(title.trim() || preview.summary.slice(0, MAX_TITLE), preview.config);
    setAdding(false);
    if (problem) setError(problem);
    else onClose();
  }

  function editFirst() {
    if (preview) onEditFirst(title.trim() || preview.summary.slice(0, MAX_TITLE), preview.config);
    else if (failedConfig) onEditFirst(failedConfig.title, failedConfig.config);
  }

  const ready = enabled === true && !ollamaProblem && !checking && !!chatName;

  return (
    <Dialog
      open
      onClose={onClose}
      title="Build a panel with AI"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button icon={<Pencil size={16} />} onClick={editFirst} disabled={running || (!preview && !failedConfig)}>
            Edit before adding
          </Button>
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={add}
            loading={adding}
            disabled={running || !preview || !canAdd}
            title={canAdd ? undefined : "This dashboard has the most panels it can hold"}
          >
            Add to dashboard
          </Button>
        </>
      }
    >
      <div className="space-y-4 pb-2">
        {enabled === false && <ErrorNote>The AI panel builder is turned off for now.</ErrorNote>}

        {ollamaProblem && (
          <OllamaSetup
            problem={ollamaProblem}
            url={ollamaUrl}
            checking={checking}
            onRetry={checkAgain}
            onUrlChange={changeOllamaUrl}
            models={["llama3.2", "nomic-embed-text"]}
          />
        )}

        {!ollamaProblem && chatModels.length > 0 && (
          <div className="flex flex-wrap gap-3">
            <Field label="Chat model" className="min-w-48 flex-1">
              <Select
                value={chatName}
                disabled={running}
                onChange={(e) => {
                  setChatName(e.target.value);
                  remember(CHAT_MODEL_KEY, e.target.value);
                }}
                className="w-full"
              >
                {chatModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Merchant lookup" hint="Optional: finds a merchant by meaning in your Ask index." className="min-w-48 flex-1">
              <Select
                value={embedName}
                disabled={running}
                onChange={(e) => {
                  setEmbedName(e.target.value);
                  // "None" is not saved: the key is shared with Ask and Categorize, which need a model.
                  if (e.target.value) remember(EMBED_MODEL_KEY, e.target.value);
                }}
                className="w-full"
              >
                <option value={NO_EMBEDDER}>None</option>
                {embedModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        )}

        {log.length > 0 && (
          <ol className="space-y-1.5 text-sm" aria-label="Conversation">
            {log.map((entry, index) => (
              <li key={index} className={entry.from === "you" ? "font-medium" : "text-ink-2"}>
                <span className="mr-1.5 text-xs font-semibold tracking-wide text-muted uppercase">
                  {entry.from === "you" ? "You" : "AI"}
                </span>
                {entry.text}
              </li>
            ))}
          </ol>
        )}

        {notPanel !== null && (
          <p className="text-sm">
            For questions, use{" "}
            <Link href="/ask" className="font-medium underline">
              Ask your transactions
            </Link>
            .
          </p>
        )}

        {preview && <AgentPreview preview={preview} title={title} onTitle={setTitle} categoryColors={categoryColors} />}

        {error && <ErrorNote>{error}</ErrorNote>}

        <form onSubmit={send} className="flex flex-wrap items-end gap-2">
          <Field label={preview ? "Change it" : "Describe the panel"} className="min-w-64 flex-1">
            <Input
              value={message}
              maxLength={MAX_MESSAGE}
              disabled={!ready || running}
              placeholder={preview ? "e.g. make it a line, only last month" : "e.g. monthly food spend this year as bars"}
              onChange={(e) => setMessage(e.target.value)}
            />
          </Field>
          {running ? (
            <Button type="button" icon={<CircleStop size={16} />} onClick={() => abort.current?.abort()}>
              Stop
            </Button>
          ) : (
            <Button type="submit" variant="primary" icon={<Sparkles size={16} />} disabled={!ready || !message.trim()}>
              {preview ? "Change" : "Build"}
            </Button>
          )}
        </form>

        {running && progress && (
          <p className="flex items-center gap-2 text-sm text-ink-2" role="status">
            <Spinner size={15} /> {progress}… A local model can take a minute.
          </p>
        )}
      </div>
    </Dialog>
  );
}
