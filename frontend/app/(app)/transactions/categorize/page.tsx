"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PartyPopper, Play, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { recall, remember } from "@/lib/storage";
import type {
  ApplyResult,
  Category,
  CategorizePreview,
  EmbeddingModel,
  Proposal,
} from "@/lib/types";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/Feedback";
import { Checkbox, Field, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { MoneyCell, Table, Td, Th, Tr } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";

const MODELS_URL = "/api/ai/models/";
const PREVIEW_URL = "/api/ai/categorize/preview/";
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
  const [setupError, setSetupError] = useState<string | null>(null);
  const [loadingSetup, setLoadingSetup] = useState(true);

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
    async function load() {
      try {
        const [categoryRes, modelRes] = await Promise.all([
          apiFetch("/api/categories/"),
          apiFetch(MODELS_URL),
        ]);
        if (cancelled) return;
        if (categoryRes.ok) setCategories(await categoryRes.json());
        if (modelRes.ok) {
          const body: { models: EmbeddingModel[] } = await modelRes.json();
          setModels(body.models);
          const saved = recall(MODEL_KEY);
          setModel(body.models.find((m) => m.name === saved)?.name ?? body.models[0]?.name ?? "");
        } else {
          // The server's message says what to do, e.g. "Run: ollama pull nomic-embed-text".
          setSetupError(await readError(modelRes, "Could not load your Ollama models."));
        }
      } catch {
        if (!cancelled) setSetupError("Cannot reach the server.");
      } finally {
        if (!cancelled) setLoadingSetup(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  function changeModel(value: string) {
    setModel(value);
    remember(MODEL_KEY, value);
  }

  async function runPreview() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch(PREVIEW_URL, {
        method: "POST",
        body: JSON.stringify({ model }),
      });
      if (!res.ok) {
        setError(await readError(res, "Could not run the preview."));
        return;
      }
      const data: CategorizePreview = await res.json();
      setPreview(data);
      setRows(data.proposals);
      // Only rows the AI is confident about start selected; the rest are the user's call.
      setChecked(new Set(data.proposals.filter((p) => p.decision === "propose").map((p) => p.transaction)));
      setChoice(
        Object.fromEntries(
          data.proposals.filter((p) => p.category).map((p) => [p.transaction, p.category as string]),
        ),
      );
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setRunning(false);
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
        subtitle="Runs on the Ollama installed on your own machine. Nothing is sent anywhere else, and nothing changes until you press Apply. What you approve counts as your own choice and helps categorise the rest."
      />

      {loadingSetup && <Loading />}
      {setupError && <ErrorNote className="mb-4">{setupError}</ErrorNote>}

      {!loadingSetup && !setupError && (
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
            {running ? "Working…" : preview ? "Run again" : "Run preview"}
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
