"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type DragEvent } from "react";
import { ArrowLeft, ArrowRight, FileUp, GripVertical, Receipt, Sparkles, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/cn";
import { readError } from "@/lib/errors";
import { money } from "@/lib/format";
import type { Category, Page, Transaction } from "@/lib/types";
import { BucketBar, TXN_DRAG_TYPE } from "@/components/transactions/BucketBar";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { MoneyCell, Table, Td, Th, Tr } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";

const URL = "/api/transactions/";
const BULK_URL = "/api/transactions/bulk-category/";
const PAGE_SIZE = 50; // matches TransactionPagination on the backend

// useSearchParams needs a Suspense boundary, or the production build refuses to prerender.
export default function TransactionsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Transactions />
    </Suspense>
  );
}

// The little "3 transactions" pill that follows the pointer while dragging rows.
function dragBadge(count: number): HTMLElement {
  const el = document.createElement("div");
  el.textContent = count === 1 ? "1 transaction" : `${count} transactions`;
  el.style.cssText =
    "position:fixed;top:-100px;left:-100px;padding:6px 12px;border:1.5px solid #111;border-radius:999px;" +
    "background:#111;color:#fff;font:600 13px system-ui,sans-serif;box-shadow:3px 3px 0 #111;";
  document.body.appendChild(el);
  return el;
}

function Transactions() {
  // A dashboard chart click opens this page as /transactions?from=..&to=..&type=..&category=..
  // so the filters start from the URL. After that they are ordinary page state.
  const searchParams = useSearchParams();
  const toast = useToast();
  const [data, setData] = useState<Page<Transaction> | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [page, setPage] = useState(1);
  const [from, setFrom] = useState(() => searchParams.get("from") ?? "");
  const [to, setTo] = useState(() => searchParams.get("to") ?? "");
  const [type, setType] = useState(() => searchParams.get("type") ?? "");
  const [categoryFilter, setCategoryFilter] = useState(() => searchParams.get("category") ?? "");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editingNotesId, setEditingNotesId] = useState<string | null>(null);
  const [editNotes, setEditNotes] = useState("");

  // Selection and drag-to-bucket.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dragCount, setDragCount] = useState(0);
  const lastClicked = useRef<number | null>(null); // for shift-click ranges
  const shiftHeld = useRef(false);

  // Categories are needed for the buckets and for every row's dropdown.
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
        if (res.ok) {
          setData(await res.json());
          setSelected(new Set()); // a selection only makes sense for the rows on screen
          lastClicked.current = null;
        } else if (res.status === 404 && page > 1) setPage(1); // page vanished (e.g. after deletes)
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
  }, [page, from, to, type, categoryFilter, reloadKey]);

  // Changing any filter goes back to page 1.
  function changeFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setPage(1);
  }

  async function patch(txn: Transaction, body: Partial<{ name: string; category: string; notes: string }>) {
    const res = await apiFetch(`${URL}${txn.id}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      toast.error(await readError(res, "Could not save the change."));
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

  // --- moving rows into a bucket --------------------------------------------------

  async function bulkMove(ids: string[], categoryId: string): Promise<boolean> {
    try {
      const res = await apiFetch(BULK_URL, {
        method: "POST",
        body: JSON.stringify({ transactions: ids, category: categoryId }),
      });
      if (res.ok) return true;
      toast.error(await readError(res, "Could not move the transactions."));
    } catch {
      toast.error("Cannot reach the server.");
    }
    return false;
  }

  // Show the new categories at once, save in one request, and offer Undo.
  async function moveInto(categoryId: string, ids: string[]) {
    const rows = data?.results.filter((t) => ids.includes(t.id) && t.category !== categoryId) ?? [];
    const target = categories.find((c) => c.id === categoryId);
    if (!rows.length || !target) return;

    const previous = new Map(rows.map((t) => [t.id, t.category]));
    const paint = (pick: (t: Transaction) => string) =>
      setData((current) =>
        current
          ? { ...current, results: current.results.map((t) => (previous.has(t.id) ? { ...t, category: pick(t) } : t)) }
          : current,
      );

    paint(() => categoryId); // optimistic
    setSelected(new Set());
    if (!(await bulkMove([...previous.keys()], categoryId))) {
      paint((t) => previous.get(t.id) ?? t.category); // put them back
      return;
    }
    // With a bucket filter on, the moved rows no longer belong on this page.
    if (categoryFilter && categoryFilter !== categoryId) setReloadKey((k) => k + 1);

    toast.success(
      `Moved ${rows.length === 1 ? "1 transaction" : `${rows.length} transactions`} to ${target.name}.`,
      {
        action: {
          label: "Undo",
          onClick: async () => {
            // Rows may have come from different categories: one request per original category.
            const byCategory = new Map<string, string[]>();
            for (const [id, category] of previous) byCategory.set(category, [...(byCategory.get(category) ?? []), id]);
            const results = await Promise.all([...byCategory].map(([category, list]) => bulkMove(list, category)));
            if (results.every(Boolean)) toast.success("Undone.");
            setReloadKey((k) => k + 1);
          },
        },
      },
    );
  }

  // --- selection --------------------------------------------------------------------

  function toggleRow(index: number, checked: boolean) {
    const rows = data?.results ?? [];
    // Shift-click selects (or clears) everything between the last click and this one. Work the
    // range out now: the state updater below runs later, after lastClicked has moved on.
    const anchor = lastClicked.current;
    const range =
      shiftHeld.current && anchor !== null
        ? rows.slice(Math.min(anchor, index), Math.max(anchor, index) + 1)
        : [rows[index]];
    const ids = range.filter(Boolean).map((row) => row.id);
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
    lastClicked.current = index;
    shiftHeld.current = false;
  }

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(data?.results.map((t) => t.id)) : new Set());
  }

  // Dragging a selected row drags the whole selection; dragging any other row drags just it.
  function onRowDragStart(event: DragEvent, txn: Transaction) {
    const ids = selected.has(txn.id) ? [...selected] : [txn.id];
    event.dataTransfer.setData(TXN_DRAG_TYPE, JSON.stringify(ids));
    event.dataTransfer.effectAllowed = "move";
    const badge = dragBadge(ids.length);
    event.dataTransfer.setDragImage(badge, 12, 12);
    setTimeout(() => badge.remove(), 0); // the browser has taken its snapshot by now
    setDragCount(ids.length);
  }

  const colorOf = (id: string) => categories.find((c) => c.id === id)?.color;
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1;
  const filtered = !!(from || to || type || categoryFilter);
  const rows = data?.results ?? [];
  const allSelected = rows.length > 0 && rows.every((t) => selected.has(t.id));
  const someSelected = selected.size > 0;

  return (
    <>
      <PageHeader
        title="Transactions"
        subtitle="Drag rows onto a bucket to categorise them. Click a name or note to edit it."
        actions={
          <>
            <Link href="/transactions/categorize" className={buttonClass("secondary", "md")}>
              <Sparkles size={16} aria-hidden /> Categorize with AI
            </Link>
            <Link href="/transactions/import" className={buttonClass("primary", "md")}>
              <FileUp size={16} aria-hidden /> Import statement
            </Link>
          </>
        }
      />

      <Card className="mb-4 flex flex-wrap items-end gap-3 p-4!">
        <Field label="From" className="w-40">
          <Input dense type="date" value={from} onChange={(e) => changeFilter(setFrom, e.target.value)} />
        </Field>
        <Field label="To" className="w-40">
          <Input dense type="date" value={to} onChange={(e) => changeFilter(setTo, e.target.value)} />
        </Field>
        <Field label="Type" className="w-36">
          <Select dense className="w-full" value={type} onChange={(e) => changeFilter(setType, e.target.value)}>
            <option value="">All</option>
            <option value="credit">Money in</option>
            <option value="debit">Money out</option>
          </Select>
        </Field>
        {filtered && (
          <Button
            size="sm"
            variant="ghost"
            icon={<X size={14} />}
            onClick={() => {
              setFrom("");
              setTo("");
              setType("");
              setCategoryFilter("");
              setPage(1);
            }}
          >
            Clear filters
          </Button>
        )}
      </Card>

      <BucketBar
        categories={categories}
        activeId={categoryFilter}
        dragCount={dragCount}
        onFilter={(id) => changeFilter(setCategoryFilter, id)}
        onDropInto={moveInto}
      />

      {/* What to do with the selection, for keyboards and touch screens (no dragging needed). */}
      {someSelected && (
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md border-[1.5px] border-ink bg-ink px-4 py-2 text-sm text-white shadow-hard-sm">
          <span className="font-semibold">{selected.size} selected</span>
          <label className="flex items-center gap-2">
            Move to
            <select
              className="h-8 rounded-sm border-[1.5px] border-white bg-ink px-2 text-white"
              value=""
              onChange={(e) => e.target.value && moveInto(e.target.value, [...selected])}
            >
              <option value="">Choose a category…</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <span className="hidden text-white/60 sm:inline">or drag them onto a bucket</span>
          <button type="button" className="ml-auto underline underline-offset-2" onClick={() => setSelected(new Set())}>
            Clear selection
          </button>
        </div>
      )}

      {error && <ErrorNote className="mb-4">{error}</ErrorNote>}

      {loading && !data && <Loading />}

      {data && data.results.length === 0 && !loading ? (
        <EmptyState
          icon={<Receipt size={22} aria-hidden />}
          title={filtered ? "Nothing matches these filters" : "No transactions yet"}
          action={
            !filtered && (
              <Link href="/transactions/import" className={buttonClass("primary", "md")}>
                Import a statement
              </Link>
            )
          }
        >
          {filtered ? "Try another bucket, widen the dates or clear a filter." : "Import a bank statement to get started."}
        </EmptyState>
      ) : (
        data && (
          <Table>
            <thead>
              <Tr className="hover:bg-transparent">
                <Th className="w-10">
                  <Checkbox aria-label="Select all on this page" checked={allSelected} onChange={toggleAll} />
                </Th>
                <Th>Date</Th>
                <Th>Name</Th>
                <Th align="right">Amount</Th>
                <Th align="right">Balance</Th>
                <Th>Category</Th>
                <Th>Notes</Th>
              </Tr>
            </thead>
            <tbody className={loading ? "opacity-50 transition-opacity" : "transition-opacity"}>
              {data.results.map((txn, index) => {
                const isSelected = selected.has(txn.id);
                const editing = editingId === txn.id || editingNotesId === txn.id;
                return (
                  <Tr
                    key={txn.id}
                    draggable={!editing}
                    onDragStart={(e) => onRowDragStart(e, txn)}
                    onDragEnd={() => setDragCount(0)}
                    className={cn(
                      "group",
                      !editing && "cursor-grab active:cursor-grabbing",
                      isSelected && "bg-[#fff8db] hover:bg-[#fff3c4]",
                    )}
                  >
                    <Td className="w-10">
                      {/* Shift is read on mouse-down here: the checkbox's own click arrives forwarded
                          from its label, and a forwarded click does not carry the Shift key. */}
                      <span
                        className="flex items-center gap-1 select-none"
                        onMouseDown={(e) => {
                          shiftHeld.current = e.shiftKey;
                        }}
                      >
                        <GripVertical size={14} className="-ml-1 text-muted opacity-0 group-hover:opacity-100" aria-hidden />
                        <Checkbox
                          aria-label={`Select ${txn.name}`}
                          checked={isSelected}
                          onKeyDown={() => {
                            shiftHeld.current = false; // Space on a focused box: one row only
                          }}
                          onChange={(checked) => toggleRow(index, checked)}
                        />
                      </span>
                    </Td>
                    <Td className="whitespace-nowrap text-ink-2">{txn.date}</Td>
                    <Td title={txn.description} className="max-w-72">
                      {editingId === txn.id ? (
                        <Input
                          dense
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
                          className="block max-w-full truncate rounded-sm text-left font-medium hover:underline"
                          onClick={() => {
                            setEditingId(txn.id);
                            setEditName(txn.name);
                          }}
                        >
                          {txn.name}
                        </button>
                      )}
                    </Td>
                    <MoneyCell value={txn.amount} type={txn.txn_type} />
                    <Td align="right" className="whitespace-nowrap text-ink-2">
                      {txn.balance === null ? "" : money(txn.balance)}
                    </Td>
                    <Td>
                      <span className="flex items-center gap-2">
                        <span
                          aria-hidden
                          className="size-3 shrink-0 rounded-full border border-ink"
                          style={{ backgroundColor: colorOf(txn.category) }}
                        />
                        <Select
                          dense
                          value={txn.category}
                          aria-label={`Category for ${txn.name}`}
                          onChange={(e) => patch(txn, { category: e.target.value })}
                        >
                          {categories.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                        </Select>
                      </span>
                    </Td>
                    <Td>
                      {editingNotesId === txn.id ? (
                        <Input
                          dense
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
                          className={`block max-w-56 truncate rounded-sm text-left hover:underline ${txn.notes ? "" : "text-muted"}`}
                          title={txn.notes || "Add a note. It is encrypted, and the AI can read it."}
                          onClick={() => {
                            setEditingNotesId(txn.id);
                            setEditNotes(txn.notes);
                          }}
                        >
                          {txn.notes || "Add note"}
                        </button>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        )
      )}

      {data && data.count > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-ink-2">{data.count.toLocaleString("en-IN")} transactions</span>
          <div className="flex items-center gap-3">
            <Button size="sm" icon={<ArrowLeft size={14} />} disabled={!data.previous || loading} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <span className="tabular-nums">
              Page {page} of {totalPages}
            </span>
            <Button size="sm" disabled={!data.next || loading} onClick={() => setPage(page + 1)}>
              Next <ArrowRight size={14} aria-hidden />
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
