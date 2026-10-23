"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PartyPopper, Play, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { embed, listEmbeddingModels, OllamaError, savedOllamaUrl, saveOllamaUrl } from "@/lib/ollama";
import { buildProposals } from "@/lib/scoring";
import { recall, remember } from "@/lib/storage";
import type {
  ApplyResult,
  Category,
  CategorizePreview,
  EmbeddingModel,
  PreparedRun,
  Proposal,
} from "@/lib/types";
import { OllamaSetup } from "@/components/ai/OllamaSetup";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/Feedback";
import { Checkbox, Field, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { MoneyCell, Table, Td, Th, Tr } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";

const PREPARE_URL = "/api/ai/categorize/prepare/";
const APPLY_URL = "/api/ai/categorize/apply/";

const MODEL_KEY = "polycoin.ai.model";

// Why a row isn't pre-selected; null for rows the AI is confident about.
function reasonFor(p: Proposal): string | null {
  if (p.decision === "below_threshold") return "Not confident enough";
  if (p.decision === "too_close") return `Too close to ${p.runner_up_name ?? "another category"}`;
  if (p.decision === "no_candidates") return "No categories to choose from";
  return null;
}

export default function Categorize() {
  const toast = useToast();
  const [models, setModels] = useState<EmbeddingModel[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [model, setModel] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState(savedOllamaUrl);
  const [setupError, setSetupError] = useState<string | null>(null); // our server
  const [ollamaProblem, setOllamaProblem] = useState<OllamaError | null>(null); // the user's Ollama
  const [loadingSetup, setLoadingSetup] = useState(true);
  const [attempt, setAttempt] = useState(0); // bumped by "Check again"
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  const [preview, setPreview] = useState<CategorizePreview | null>(null);
  const [rows, setRows] = useState<Proposal[]>([]); // proposals still on screen
  const [checked, setChecked] = useState<Set<string>>(new Set()); // transaction ids to apply
  const [choice, setChoice] = useState<Record<string, string>>({}); // transaction id -> category id
  const [result, setResult] = useState<ApplyResult | null>(null);

  const [running, setRunning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // "Others" is where rows start; it is never a target, so it isn't offered.
  const choosable = categories.filter((c) => !c.is_default);
  const selected = rows.filter((r) => checked.has(r.transaction) && choice[r.transaction]);
  const stale = preview !== null && preview.model !== model;

  useEffect(() => {
    let cancelled = false;
    async function loadCategories() {
      try {
        const res = await apiFetch("/api/categories/");
        if (cancelled) return;
        if (res.ok) setCategories(await res.json());
        else setSetupError(await readError(res, "Could not load your categories."));
      } catch {
        if (!cancelled) setSetupError("Cannot reach the server.");
      }
    }
    // Straight from this browser to the user's own Ollama; our server is not involved.
    async function loadModels() {
      try {
        const found: EmbeddingModel[] = await listEmbeddingModels(ollamaUrl);
        if (cancelled) return;
        setOllamaProblem(null);
        setModels(found);
        const saved = recall(MODEL_KEY);
        setModel(found.find((m) => m.name === saved)?.name ?? found[0]?.name ?? "");
      } catch (problem) {
        if (cancelled) return;
        setOllamaProblem(
          problem instanceof OllamaError ? problem : new OllamaError("unreachable", "Can't reach Ollama on this computer."),
        );
      }
    }
    Promise.all([loadCategories(), loadModels()]).finally(() => {
      if (!cancelled) setLoadingSetup(false);
    });
    return () => {
      cancelled = true;
    };
  }, [ollamaUrl, attempt]);

  function changeModel(value: string) {
    setModel(value);
    remember(MODEL_KEY, value);
  }

  function checkAgain() {
    setLoadingSetup(true);
    setAttempt((n) => n + 1);
  }

  function changeOllamaUrl(url: string) {
    saveOllamaUrl(url);
    setOllamaUrl(url);
    checkAgain(); // also re-checks when the address didn't actually change
  }

  async function runPreview() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      // 1. Our server decrypts the rows and returns the texts to embed (no Ollama call there).
      const res = await apiFetch(PREPARE_URL);
      if (!res.ok) {
        setError(await readError(res, "Could not prepare the run."));
        return;
      }
      const run: PreparedRun = await res.json();
      // 2. The user's own Ollama embeds them, and 3. this browser scores them.
      setProgress({ done: 0, total: run.texts.length });
      const vectors = await embed(ollamaUrl, model, run.texts, (done) =>
        setProgress({ done, total: run.texts.length }),
      );
      const data: CategorizePreview = buildProposals(run, vectors, model);
      setPreview(data);
      setRows(data.proposals);
      // Only rows the AI is confident about start selected; the rest are the user's call.
      setChecked(new Set(data.proposals.filter((p) => p.decision === "propose").map((p) => p.transaction)));
      setChoice(
        Object.fromEntries(
          data.proposals.filter((p) => p.category).map((p) => [p.transaction, p.category as string]),
        ),
      );
    } catch (problem) {
      if (problem instanceof OllamaError) {
        setError(problem.code === "unreachable" ? `${problem.message} Is it still running?` : problem.message);
      } else if (problem instanceof TypeError) {
        setError("Cannot reach the server."); // fetch itself failed
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setRunning(false);
      setProgress(null);
    }
  }

  function toggle(id: string) {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Picking a category is an explicit decision, so it also selects the row.
  function pick(id: string, categoryId: string) {
    setChoice((current) => ({ ...current, [id]: categoryId }));
    setChecked((current) => {
      const next = new Set(current);
      if (categoryId) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function apply() {
    setApplying(true);
    setError(null);
    try {
      const res = await apiFetch(APPLY_URL, {
        method: "POST",
        body: JSON.stringify({
          decisions: selected.map((r) => ({ transaction: r.transaction, category: choice[r.transaction] })),
        }),
      });
      if (!res.ok) {
        setError(await readError(res, "Could not apply the changes."));
        return;
      }
      const data: ApplyResult = await res.json();
      setResult(data);
      toast.success(`Categorised ${data.applied} transactions.`);
      // Rows the server applied leave the table; skipped ones stay so nothing disappears unseen.
      const skipped = new Set(data.skipped.map((s) => s.transaction));
      const done = new Set(selected.map((r) => r.transaction).filter((id) => !skipped.has(id)));
      setRows((current) => current.filter((r) => !done.has(r.transaction)));
      setChecked((current) => new Set([...current].filter((id) => !done.has(id))));
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setApplying(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Categorize with AI"
        subtitle="The AI model runs on your computer: transaction text goes from this browser to your Ollama, never to an AI service. Nothing changes until you press Apply. What you approve counts as your own choice and helps categorise the rest."
      />

      {loadingSetup && !ollamaProblem && <Loading />}
      {setupError && <ErrorNote className="mb-4">{setupError}</ErrorNote>}
      {ollamaProblem && !setupError && (
        <OllamaSetup
          problem={ollamaProblem}
          url={ollamaUrl}
          checking={loadingSetup}
          onRetry={checkAgain}
          onUrlChange={changeOllamaUrl}
        />
      )}

      {!loadingSetup && !setupError && !ollamaProblem && (
        <Card className="mb-5 flex flex-wrap items-end gap-3 p-4!">
          <Field label="Embedding model" className="w-64">
            <Select dense className="w-full" value={model} onChange={(e) => changeModel(e.target.value)}>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </Select>
          </Field>
          <Button
            variant="primary"
            loading={running}
            disabled={!model || applying}
            icon={preview ? <RefreshCw size={16} /> : <Play size={16} />}
            onClick={runPreview}
          >
            {running
              ? progress && progress.total > 0
                ? `Embedding ${progress.done} / ${progress.total}…`
                : "Working…"
              : preview
                ? "Run again"
                : "Run preview"}
          </Button>
        </Card>
      )}

      {stale && !running && <p className="mb-3 text-sm text-ink-2">The model changed since this preview. Run again to use it.</p>}
      {error && <ErrorNote className="mb-4">{error}</ErrorNote>}

      {preview && (
        <section className="space-y-3">
          <p className="text-sm text-ink-2">
            <strong className="text-ink">{preview.considered}</strong> uncategorised scored:{" "}
            <strong className="text-ink">{preview.proposed}</strong> proposed, {preview.skipped} left for you.
            {preview.capped && " More remain: apply these, then run again to continue."}
          </p>

          {result && result.skipped.length > 0 && (
            <ErrorNote>{result.skipped.length} skipped (changed since the preview). Run again to refresh.</ErrorNote>
          )}

          {rows.length > 0 ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  onClick={() => setChecked(new Set(rows.filter((r) => choice[r.transaction]).map((r) => r.transaction)))}
                >
                  Select all with a category
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setChecked(new Set())}>
                  Select none
                </Button>
              </div>

              <Table>
                <thead>
                  <Tr className="hover:bg-transparent">
                    <Th>
                      <span className="sr-only">Apply</span>
                    </Th>
                    <Th>Date</Th>
                    <Th>Name</Th>
                    <Th align="right">Amount</Th>
                    <Th>Category</Th>
                    <Th align="right">Score</Th>
                    <Th>Note</Th>
                  </Tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const id = row.transaction;
                    const reason = reasonFor(row);
                    return (
                      <Tr key={id}>
                        <Td>
                          <Checkbox
                            aria-label={`Apply to ${row.name}`}
                            checked={checked.has(id)}
                            disabled={!choice[id]}
                            onChange={() => toggle(id)}
                          />
                        </Td>
                        <Td className="whitespace-nowrap text-ink-2">{row.date}</Td>
                        <Td className="font-medium">{row.name}</Td>
                        <MoneyCell value={row.amount} type={row.txn_type} />
                        <Td>
                          <Select
                            dense
                            value={choice[id] ?? ""}
                            aria-label={`Category for ${row.name}`}
                            onChange={(e) => pick(id, e.target.value)}
                          >
                            <option value="">(choose)</option>
                            {choosable.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </Select>
                        </Td>
                        <Td
                          align="right"
                          className="whitespace-nowrap text-ink-2"
                          title={
                            row.runner_up_name && row.runner_up_score !== null
                              ? `Runner-up: ${row.runner_up_name} (${row.runner_up_score.toFixed(2)})`
                              : undefined
                          }
                        >
                          {row.score !== null ? row.score.toFixed(2) : ""}
                        </Td>
                        <Td className="text-muted">{reason}</Td>
                      </Tr>
                    );
                  })}
                </tbody>
              </Table>

              <Button variant="primary" loading={applying} disabled={selected.length === 0 || running} onClick={apply}>
                {applying ? "Applying…" : `Apply ${selected.length} selected`}
              </Button>
            </>
          ) : (
            <EmptyState icon={<PartyPopper size={22} aria-hidden />} title="All done here">
              Nothing left to categorise in this batch.
              <br />
              <Link href="/transactions" className={buttonClass("secondary", "sm", "mt-3")}>
                View transactions
              </Link>
            </EmptyState>
          )}
        </section>
      )}
    </>
  );
}
