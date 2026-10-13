"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
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

const MODELS_URL = "/api/ai/models/";
const PREVIEW_URL = "/api/ai/categorize/preview/";
const APPLY_URL = "/api/ai/categorize/apply/";

const MODEL_KEY = "polycoin.ai.model";

function money(value: string) {
  return Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

// Why a row isn't pre-selected; null for rows the AI is confident about.
function reasonFor(p: Proposal): string | null {
  if (p.decision === "below_threshold") return "Not confident enough";
  if (p.decision === "too_close") return `Too close to ${p.runner_up_name ?? "another category"}`;
  if (p.decision === "no_candidates") return "No categories to choose from";
  return null;
}

export default function Categorize() {
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
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Categorize with AI</h1>
        <Link href="/transactions" className="text-sm underline">Transactions</Link>
      </div>

      <p className="text-xs text-gray-500">
        Runs on the Ollama installed on your own machine. Nothing is sent anywhere else, and nothing
        is changed until you press Apply. What you approve counts as your own choice and helps
        categorise the rest.
      </p>

      {loadingSetup && <p className="text-gray-500">Loading...</p>}
      {setupError && <p className="text-red-600">{setupError}</p>}

      {!loadingSetup && !setupError && (
        <section className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            Embedding model
            <select className="border p-1" value={model} onChange={(e) => changeModel(e.target.value)}>
              {models.map((m) => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </select>
          </label>
          <button
            onClick={runPreview}
            disabled={!model || running || applying}
            className="bg-black text-white px-4 py-2 disabled:opacity-50"
          >
            {running ? "Working..." : preview ? "Run again" : "Run preview"}
          </button>
        </section>
      )}

      {stale && !running && (
        <p className="text-sm text-gray-500">
          The model changed since this preview. Run again to use it.
        </p>
      )}
      {error && <p className="text-red-600">{error}</p>}

      {preview && (
        <section className="flex flex-col gap-2">
          <p className="text-sm">
            {preview.considered} uncategorised scored: {preview.proposed} proposed,{" "}
            {preview.skipped} left for you.
            {preview.capped && " More remain: apply these, then run again to continue."}
          </p>

          {result && (
            <p className="text-sm text-green-700">
              Applied {result.applied}.
              {result.skipped.length > 0 &&
                ` ${result.skipped.length} skipped (changed since the preview). Run again to refresh.`}
            </p>
          )}

          {rows.length > 0 ? (
            <>
              <div className="flex flex-wrap items-center gap-4 text-sm">
                <button
                  className="underline"
                  onClick={() => setChecked(new Set(rows.filter((r) => choice[r.transaction]).map((r) => r.transaction)))}
                >
                  Select all with a category
                </button>
                <button className="underline" onClick={() => setChecked(new Set())}>
                  Select none
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="p-2"><span className="sr-only">Apply</span></th>
                      <th className="p-2">Date</th>
                      <th className="p-2">Name</th>
                      <th className="p-2 text-right">Amount</th>
                      <th className="p-2">Category</th>
                      <th className="p-2 text-right">Score</th>
                      <th className="p-2">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const id = row.transaction;
                      const reason = reasonFor(row);
                      return (
                        <tr key={id} className="border-b">
                          <td className="p-2">
                            <input
                              type="checkbox"
                              aria-label={`Apply to ${row.name}`}
                              checked={checked.has(id)}
                              disabled={!choice[id]}
                              onChange={() => toggle(id)}
                            />
                          </td>
                          <td className="p-2 whitespace-nowrap">{row.date}</td>
                          <td className="p-2">{row.name}</td>
                          <td className={`p-2 text-right whitespace-nowrap ${row.txn_type === "credit" ? "text-green-600" : "text-red-600"}`}>
                            {row.txn_type === "credit" ? "+" : "-"}{money(row.amount)}
                          </td>
                          <td className="p-2">
                            <select
                              className="border p-1"
                              value={choice[id] ?? ""}
                              onChange={(e) => pick(id, e.target.value)}
                            >
                              <option value="">(choose)</option>
                              {choosable.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                            </select>
                          </td>
                          <td
                            className="p-2 text-right whitespace-nowrap"
                            title={
                              row.runner_up_name && row.runner_up_score !== null
                                ? `Runner-up: ${row.runner_up_name} (${row.runner_up_score.toFixed(2)})`
                                : undefined
                            }
                          >
                            {row.score !== null ? row.score.toFixed(2) : ""}
                          </td>
                          <td className="p-2 text-gray-500">{reason}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <button
                onClick={apply}
                disabled={selected.length === 0 || applying || running}
                className="self-start bg-black text-white px-4 py-2 disabled:opacity-50"
              >
                {applying ? "Applying..." : `Apply ${selected.length} selected`}
              </button>
            </>
          ) : (
            <p className="p-4 text-center text-gray-500">
              Nothing left to categorise here. <Link href="/transactions" className="underline">View transactions</Link>.
            </p>
          )}
        </section>
      )}
    </main>
  );
}
