"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import type { Category, Page, Transaction } from "@/lib/types";

const URL = "/api/transactions/";
const PAGE_SIZE = 50; // matches TransactionPagination on the backend

function money(value: string | null) {
  if (value === null) return "";
  return Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

// useSearchParams needs a Suspense boundary, or the production build refuses to prerender.
export default function TransactionsPage() {
  return (
    <Suspense fallback={<main className="p-6 text-gray-500">Loading...</main>}>
      <Transactions />
    </Suspense>
  );
}

function Transactions() {
  // A dashboard chart click opens this page as /transactions?from=..&to=..&type=..&category=..
  // so the filters start from the URL. After that they are ordinary page state.
  const searchParams = useSearchParams();
  const [data, setData] = useState<Page<Transaction> | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [from, setFrom] = useState(() => searchParams.get("from") ?? "");
  const [to, setTo] = useState(() => searchParams.get("to") ?? "");
  const [type, setType] = useState(() => searchParams.get("type") ?? "");
  const [categoryFilter, setCategoryFilter] = useState(() => searchParams.get("category") ?? "");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editingNotesId, setEditingNotesId] = useState<string | null>(null);
  const [editNotes, setEditNotes] = useState("");

  // Categories are needed for the filter and for every row's dropdown.
  useEffect(() => {
    async function loadCategories() {
      const res = await apiFetch("/api/categories/");
      if (res.ok) setCategories(await res.json());
    }
    loadCategories();
  }, []);

  useEffect(() => {
    let cancelled = false; // ignore a slow response that arrives after the filters changed
    async function load() {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({ page: String(page) });
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      if (type) params.set("type", type);
      if (categoryFilter) params.set("category", categoryFilter);
      try {
        const res = await apiFetch(`${URL}?${params}`);
        if (cancelled) return;
        if (res.ok) setData(await res.json());
        else if (res.status === 404 && page > 1) setPage(1); // page vanished (e.g. after deletes)
        else setError(await readError(res, "Could not load transactions."));
      } catch {
        if (!cancelled) setError("Cannot reach the server.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [page, from, to, type, categoryFilter]);

  // Changing any filter goes back to page 1.
  function changeFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setPage(1);
  }

  async function patch(txn: Transaction, body: Partial<{ name: string; category: string; notes: string }>) {
    setError(null);
    const res = await apiFetch(`${URL}${txn.id}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      setError(await readError(res, "Could not save the change."));
      return false;
    }
    const updated: Transaction = await res.json();
    setData((current) =>
      current
        ? { ...current, results: current.results.map((t) => (t.id === updated.id ? updated : t)) }
        : current,
    );
    return true;
  }

  async function saveName(txn: Transaction) {
    const name = editName.trim();
    if (name !== txn.name && !(await patch(txn, { name }))) return; // keep editing on error
    setEditingId(null);
  }

  async function saveNotes(txn: Transaction) {
    const notes = editNotes.trim();
    if (notes !== txn.notes && !(await patch(txn, { notes }))) return; // keep editing on error
    setEditingNotesId(null);
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Transactions</h1>
        <div className="flex gap-4 text-sm underline">
          <Link href="/transactions/import">Import statement</Link>
          <Link href="/transactions/categorize">Categorize with AI</Link>
          <Link href="/categories">Categories</Link>
          <Link href="/dashboard">Dashboard</Link>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col gap-1">
          From
          <input type="date" className="border p-1" value={from} onChange={(e) => changeFilter(setFrom, e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          To
          <input type="date" className="border p-1" value={to} onChange={(e) => changeFilter(setTo, e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          Type
          <select className="border p-1" value={type} onChange={(e) => changeFilter(setType, e.target.value)}>
            <option value="">All</option>
            <option value="credit">Credit</option>
            <option value="debit">Debit</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          Category
          <select className="border p-1" value={categoryFilter} onChange={(e) => changeFilter(setCategoryFilter, e.target.value)}>
            <option value="">All</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {(from || to || type || categoryFilter) && (
          <button
            className="underline"
            onClick={() => {
              setFrom("");
              setTo("");
              setType("");
              setCategoryFilter("");
              setPage(1);
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="text-red-600">{error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b">
              <th className="p-2">Date</th>
              <th className="p-2">Name</th>
              <th className="p-2 text-right">Amount</th>
              <th className="p-2 text-right">Balance</th>
              <th className="p-2">Category</th>
              <th className="p-2">Notes</th>
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {data?.results.map((txn) => (
              <tr key={txn.id} className="border-b">
                <td className="p-2 whitespace-nowrap">{txn.date}</td>
                <td className="p-2" title={txn.description}>
                  {editingId === txn.id ? (
                    <input
                      className="w-full border p-1"
                      maxLength={200}
                      value={editName}
                      autoFocus
                      onChange={(e) => setEditName(e.target.value)}
                      onBlur={() => saveName(txn)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") e.currentTarget.blur();
                        if (e.key === "Escape") setEditingId(null);
                      }}
                    />
                  ) : (
                    <button
                      className="text-left hover:underline"
                      onClick={() => {
                        setEditingId(txn.id);
                        setEditName(txn.name);
                      }}
                    >
                      {txn.name}
                    </button>
                  )}
                </td>
                <td className={`p-2 text-right whitespace-nowrap ${txn.txn_type === "credit" ? "text-green-600" : "text-red-600"}`}>
                  {txn.txn_type === "credit" ? "+" : "-"}{money(txn.amount)}
                </td>
                <td className="p-2 text-right whitespace-nowrap">{money(txn.balance)}</td>
                <td className="p-2">
                  <select
                    className="border p-1"
                    value={txn.category}
                    onChange={(e) => patch(txn, { category: e.target.value })}
                  >
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </td>
                <td className="p-2">
                  {editingNotesId === txn.id ? (
                    <input
                      className="w-full border p-1"
                      maxLength={500}
                      value={editNotes}
                      autoFocus
                      onChange={(e) => setEditNotes(e.target.value)}
                      onBlur={() => saveNotes(txn)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") e.currentTarget.blur();
                        if (e.key === "Escape") setEditingNotesId(null);
                      }}
                    />
                  ) : (
                    <button
                      className={`block max-w-56 truncate text-left hover:underline ${txn.notes ? "" : "text-gray-400"}`}
                      title={txn.notes || "Add a note. It is encrypted, and the AI can read it."}
                      onClick={() => {
                        setEditingNotesId(txn.id);
                        setEditNotes(txn.notes);
                      }}
                    >
                      {txn.notes || "Add note"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.results.length === 0 && !loading && (
          <p className="p-4 text-center text-gray-500">
            No transactions. <Link href="/transactions/import" className="underline">Import a statement</Link>.
          </p>
        )}
      </div>

      {data && data.count > 0 && (
        <div className="flex items-center justify-between text-sm">
          <span>{data.count} transactions</span>
          <div className="flex items-center gap-3">
            <button disabled={!data.previous || loading} onClick={() => setPage(page - 1)} className="underline disabled:opacity-40 disabled:no-underline">
              Previous
            </button>
            <span>Page {page} of {totalPages}</span>
            <button disabled={!data.next || loading} onClick={() => setPage(page + 1)} className="underline disabled:opacity-40 disabled:no-underline">
              Next
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
