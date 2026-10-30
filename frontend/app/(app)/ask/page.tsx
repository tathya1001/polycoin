"use client";

// Ask your transactions: a question in plain language, answered from the user's own rows.
//
// Flow (lib/rag.ts):
//   - GET  /api/ai/rag/status/    how much is indexed with the chosen embedding model
//   - sync: GET pending/ -> the user's Ollama embeds -> POST vectors/, until nothing remains
//   - ask:  the user's Ollama embeds the question -> POST ask/ (search + prompt) -> the user's
//           Ollama streams the answer. The server never calls a model.
// Nothing is kept in the browser but settings (the Ollama address and the chosen models, in
// localStorage); the question, the sources and the answer live in memory only.

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { CircleStop, MessageSquareText, SearchX } from "lucide-react";
import { loadSources } from "@/lib/dataSources";
import { money } from "@/lib/format";
import { PRESET_LABELS } from "@/lib/insights";
import { chatStream, embed, listChatModels, listEmbeddingModels, OllamaError, savedOllamaUrl, saveOllamaUrl } from "@/lib/ollama";
import { ask, httpRagApi, RagProblem, syncIndex, type SyncProgress } from "@/lib/rag";
import { recall, remember } from "@/lib/storage";
import type { AskResponse, ChatModel, DataSource, DatePreset, EmbeddingModel, RagStatus } from "@/lib/types";
import { OllamaSetup } from "@/components/ai/OllamaSetup";
import { AnswerView } from "@/components/ask/AnswerView";
import { IndexCard } from "@/components/ask/IndexCard";
import { SourcesTable, sourceRowId } from "@/components/ask/SourcesTable";
import SourcePicker from "@/components/dashboard/SourcePicker";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card, Chip } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/Confirm";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/Feedback";
import { Field, Input, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";

const EMBED_MODEL_KEY = "polycoin.ai.model"; // shared with Categorize: one embedding model for both
const CHAT_MODEL_KEY = "polycoin.ai.chatModel";
const MAX_QUESTION = 300; // the server's limit
const PERIODS: DatePreset[] = ["all", "this_month", "last_month", "last_3_months", "last_12_months", "this_year"];
const TYPES = { all: "Money in and out", debit: "Money out", credit: "Money in" } as const;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

// One readable sentence for anything that can go wrong on this page.
function explain(problem: unknown): string {
  if (problem instanceof OllamaError) {
    return problem.code === "unreachable" ? `${problem.message} Is it still running?` : problem.message;
  }
  if (problem instanceof RagProblem) {
    if (problem.code === "no_index") return "Nothing is indexed with this model yet. Press Update first.";
    if (problem.code === "dimension_mismatch") {
      return "This model's vectors don't match the saved index. Clear the index, then update it.";
    }
    if (problem.code === "rag_disabled") return "Ask is turned off for now. Please try again later.";
    return problem.message;
  }
  if (problem instanceof TypeError) return "Cannot reach the server.";
  return "Something went wrong. Please try again.";
}

// Older Ollama versions report no digest; the name alone then identifies the index.
function digestOf(model: EmbeddingModel): string {
  return model.digest ?? "unknown";
}

function pickSaved<T extends { name: string }>(models: T[], key: string): string {
  const saved = recall(key);
  return models.find((m) => m.name === saved)?.name ?? models[0]?.name ?? "";
}

export default function Ask() {
  const toast = useToast();
  const confirm = useConfirm();

  // The user's Ollama and the chosen models.
  const [ollamaUrl, setOllamaUrl] = useState(savedOllamaUrl);
  const [embedModels, setEmbedModels] = useState<EmbeddingModel[]>([]);
  const [chatModels, setChatModels] = useState<ChatModel[]>([]);
  const [embedName, setEmbedName] = useState("");
  const [chatName, setChatName] = useState("");
  const [ollamaProblem, setOllamaProblem] = useState<OllamaError | null>(null);
  const [loadingSetup, setLoadingSetup] = useState(true);
  const [attempt, setAttempt] = useState(0); // bumped by "Check again"

  // The index.
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [progress, setProgress] = useState<SyncProgress | null>(null);
  const [clearing, setClearing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const syncAbort = useRef<AbortController | null>(null);

  // The question and its answer.
  const [question, setQuestion] = useState("");
  const [preset, setPreset] = useState<DatePreset>("all");
  const [txnType, setTxnType] = useState<keyof typeof TYPES>("all");
  const [sources, setSources] = useState<DataSource[]>([]);
  const [askSources, setAskSources] = useState<string[]>([]);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [asked, setAsked] = useState(""); // the question the shown answer belongs to
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const askAbort = useRef<AbortController | null>(null);

  const embedModel = embedModels.find((m) => m.name === embedName) ?? null;

  useEffect(() => {
    let cancelled = false;
    // Straight from this browser to the user's own Ollama; our server is not involved.
    (async () => {
      try {
        const [embedding, chat] = await Promise.all([listEmbeddingModels(ollamaUrl), listChatModels(ollamaUrl)]);
        if (cancelled) return;
        setOllamaProblem(null);
        setEmbedModels(embedding);
        setChatModels(chat);
        setEmbedName(pickSaved(embedding, EMBED_MODEL_KEY));
        setChatName(pickSaved(chat, CHAT_MODEL_KEY));
      } catch (problem) {
        if (cancelled) return;
        setOllamaProblem(
          problem instanceof OllamaError ? problem : new OllamaError("unreachable", "Can't reach Ollama on this computer."),
        );
      } finally {
        if (!cancelled) setLoadingSetup(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ollamaUrl, attempt]);

  const sync = useCallback(
    async (model: EmbeddingModel) => {
      syncAbort.current?.abort();
      const controller = new AbortController();
      syncAbort.current = controller;
      setSyncing(true);
      setProgress(null);
      setIndexError(null);
      try {
        await syncIndex({
          api: httpRagApi,
          embed: (texts) => embed(ollamaUrl, model.name, texts),
          model: model.name,
          digest: digestOf(model),
          dims: model.dimension,
          onProgress: setProgress,
          signal: controller.signal,
        });
      } catch (problem) {
        if (!isAbort(problem)) setIndexError(explain(problem));
      } finally {
        // A newer sync (or a model switch) may have replaced this one; only the latest owns the
        // "syncing" state, and an aborted sync must not overwrite the next model's status.
        if (syncAbort.current === controller) syncAbort.current = null;
        if (!syncAbort.current) {
          setSyncing(false);
          setProgress(null);
        }
        if (!controller.signal.aborted) {
          try {
            setStatus(await httpRagApi.status(model.name, digestOf(model)));
          } catch {
            // the status line keeps its last value until the next refresh
          }
        }
      }
    },
    [ollamaUrl],
  );

  // The status for the chosen model, then an automatic sync when rows are missing.
  useEffect(() => {
    if (!embedModel) return;
    let cancelled = false;
    (async () => {
      try {
        const next = await httpRagApi.status(embedModel.name, digestOf(embedModel));
        if (cancelled) return;
        setStatus(next);
        setIndexError(null);
        if (next.enabled && next.indexed < next.total) void sync(embedModel);
      } catch (problem) {
        if (!cancelled) setIndexError(explain(problem));
      }
    })();
    return () => {
      cancelled = true;
      syncAbort.current?.abort();
    };
  }, [embedModel, sync]);

  useEffect(() => () => askAbort.current?.abort(), []);

  useEffect(() => {
    loadSources().then(setSources);
  }, []);

  function checkAgain() {
    setLoadingSetup(true);
    setAttempt((n) => n + 1);
  }

  function changeOllamaUrl(url: string) {
    saveOllamaUrl(url);
    setOllamaUrl(url);
    checkAgain();
  }

  async function clearIndex() {
    if (!embedModel) return;
    const ok = await confirm({
      title: "Clear the search index?",
      message: "Your transactions stay as they are. Asking needs the index, so it's rebuilt when you press Update.",
      confirmLabel: "Clear index",
      tone: "danger",
    });
    if (!ok) return;
    syncAbort.current?.abort();
    setClearing(true);
    try {
      await httpRagApi.clear();
      setStatus(await httpRagApi.status(embedModel.name, digestOf(embedModel)));
      setResponse(null);
      setAnswer("");
      toast.success("Search index cleared.");
    } catch (problem) {
      setIndexError(explain(problem));
    } finally {
      setClearing(false);
    }
  }

  async function submit(text: string, useQuestionPeriod: boolean) {
    // The status carries the model's query prefix; without it the question would be embedded
    // differently from the index, so asking waits until the status has loaded.
    if (!embedModel || !status || !chatName || !text.trim()) return;
    askAbort.current?.abort();
    const controller = new AbortController();
    askAbort.current = controller;
    setAsking(true);
    setStreaming(false);
    setAskError(null);
    setResponse(null);
    setAnswer("");
    setHighlighted(null);
    setAsked(text.trim());
    try {
      await ask({
        api: httpRagApi,
        embed: (texts) => embed(ollamaUrl, embedModel.name, texts),
        chat: (messages, options, onToken, signal) =>
          chatStream(ollamaUrl, chatName, messages, options, onToken, signal),
        model: embedModel.name,
        digest: digestOf(embedModel),
        queryPrefix: status.profile.query_prefix,
        question: text.trim(),
        filters: { date: { preset }, type: txnType === "all" ? null : txnType, data_sources: askSources },
        useQuestionPeriod,
        onResponse: (next) => {
          setResponse(next);
          setStreaming(next.messages !== null);
        },
        onToken: (piece) => setAnswer((current) => current + piece),
        signal: controller.signal,
      });
    } catch (problem) {
      if (!isAbort(problem)) setAskError(explain(problem));
    } finally {
      if (askAbort.current === controller) {
        askAbort.current = null;
        setAsking(false);
        setStreaming(false);
      }
    }
  }

  function cite(n: number) {
    setHighlighted(n);
    document.getElementById(sourceRowId(n))?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const ready = !loadingSetup && !ollamaProblem;
  const disabled = status !== null && !status.enabled;
  const noTransactions = status?.total === 0;

  return (
    <>
      <PageHeader
        title="Ask your transactions"
        subtitle="Ask in plain words, like “What do I pay for the gym?”. The AI model runs on your computer. The search index is stored encrypted on our server."
      />

      {loadingSetup && !ollamaProblem && <Loading />}
      {ollamaProblem && (
        <OllamaSetup
          problem={ollamaProblem}
          url={ollamaUrl}
          checking={loadingSetup}
          onRetry={checkAgain}
          onUrlChange={changeOllamaUrl}
          models={["nomic-embed-text", "llama3.2"]}
        />
      )}

      {ready && disabled && (
        <EmptyState icon={<MessageSquareText size={22} aria-hidden />} title="Ask is turned off for now">
          Your transactions and dashboards work as usual. Please try again later.
        </EmptyState>
      )}

      {ready && !disabled && (
        <>
          <Card className="mb-5 flex flex-wrap items-end gap-3 p-4!">
            <Field label="Embedding model" hint="Finds the matching transactions" className="w-64">
              <Select
                dense
                className="w-full"
                value={embedName}
                disabled={syncing}
                onChange={(e) => {
                  setEmbedName(e.target.value);
                  remember(EMBED_MODEL_KEY, e.target.value);
                }}
              >
                {embedModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Chat model" hint="Writes the answer" className="w-64">
              <Select
                dense
                className="w-full"
                value={chatName}
                onChange={(e) => {
                  setChatName(e.target.value);
                  remember(CHAT_MODEL_KEY, e.target.value);
                }}
              >
                {chatModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
          </Card>

          {status && (
            <IndexCard
              status={status}
              syncing={syncing}
              progress={progress}
              clearing={clearing}
              onUpdate={() => embedModel && void sync(embedModel)}
              onClear={clearIndex}
            />
          )}
          {indexError && <ErrorNote className="mb-4">{indexError}</ErrorNote>}

          {noTransactions ? (
            <EmptyState icon={<MessageSquareText size={22} aria-hidden />} title="No transactions yet">
              Import a bank statement first, then come back to ask about it.
              <br />
              <Link href="/transactions/import" className={buttonClass("secondary", "sm", "mt-3")}>
                Import a statement
              </Link>
            </EmptyState>
          ) : (
            <>
              <form
                className="mb-5 flex flex-wrap items-end gap-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void submit(question, true);
                }}
              >
                <Field label="Your question" className="min-w-64 flex-1">
                  <Input
                    value={question}
                    maxLength={MAX_QUESTION}
                    placeholder="When did I last pay my landlord?"
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </Field>
                <Field label="Period" className="w-44">
                  <Select className="w-full" value={preset} onChange={(e) => setPreset(e.target.value as DatePreset)}>
                    {PERIODS.map((p) => (
                      <option key={p} value={p}>
                        {PRESET_LABELS[p]}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Type" className="w-44">
                  <Select className="w-full" value={txnType} onChange={(e) => setTxnType(e.target.value as keyof typeof TYPES)}>
                    {Object.entries(TYPES).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </Field>
                {sources.length > 1 && (
                  <Field label="Data sources" className="w-auto">
                    <SourcePicker sources={sources} selected={askSources} onChange={setAskSources} />
                  </Field>
                )}
                {asking ? (
                  <Button type="button" icon={<CircleStop size={16} />} onClick={() => askAbort.current?.abort()}>
                    Stop
                  </Button>
                ) : (
                  <Button type="submit" variant="primary" disabled={!question.trim() || !chatName || !status || status.indexed === 0}>
                    Ask
                  </Button>
                )}
              </form>

              {askError && <ErrorNote className="mb-4">{askError}</ErrorNote>}
              {asking && !response && <Loading label="Searching your transactions…" />}

              {response && (
                <section className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
                    {response.period.source === "question" ? (
                      <Chip onRemove={() => void submit(asked, false)}>
                        Period: {response.period.phrase} ({response.period.from} to {response.period.to}), from your question
                      </Chip>
                    ) : (
                      <span>
                        Searched {response.period.from} to {response.period.to}
                      </span>
                    )}
                  </div>

                  {response.coverage.searched < response.coverage.indexed && (
                    <p className="text-sm text-ink-2">
                      Searched your newest {response.coverage.searched.toLocaleString("en-IN")} of{" "}
                      {response.coverage.indexed.toLocaleString("en-IN")} transactions in this period. Choose a shorter period
                      to search older ones.
                    </p>
                  )}
                  {response.coverage.indexed < response.coverage.total && (
                    <p className="text-sm text-ink-2">
                      {(response.coverage.total - response.coverage.indexed).toLocaleString("en-IN")} transactions in this
                      period aren&apos;t indexed yet, so they weren&apos;t searched.
                    </p>
                  )}

                  {response.messages === null ? (
                    <EmptyState icon={<SearchX size={22} aria-hidden />} title="No matching transactions">
                      Nothing in this period matches your question. Try other words or a longer period.
                    </EmptyState>
                  ) : (
                    <>
                      <AnswerView
                        answer={answer}
                        sources={response.sources}
                        inPrompt={response.in_prompt}
                        streaming={streaming}
                        onCite={cite}
                      />
                      <p className="text-sm text-ink-2">
                        Across {response.summary.matches} matching transactions: {money(response.summary.debit_total)} out,{" "}
                        {money(response.summary.credit_total)} in.
                      </p>
                      <details open className="space-y-2">
                        <summary className="cursor-pointer text-sm font-medium">
                          Matching transactions ({response.sources.length})
                        </summary>
                        <SourcesTable sources={response.sources} highlighted={highlighted} />
                      </details>
                    </>
                  )}
                </section>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
