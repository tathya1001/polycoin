"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Link2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { money } from "@/lib/format";
import type { TransferPair, TransferSide, TransferSuggestions } from "@/lib/types";
import { Button, buttonClass } from "@/components/ui/Button";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/Feedback";
import { Checkbox } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";

const SUGGESTIONS_URL = "/api/transactions/transfer-suggestions/";
const BULK_URL = "/api/transactions/links/bulk/";

const keyOf = (pair: TransferPair) => `${pair.debit.id}:${pair.credit.id}`;

function Side({ side }: { side: TransferSide }) {
  return (
    <>
      <span className="block font-medium">{side.data_source_name}</span>
      <span className="block max-w-56 truncate text-ink-2" title={side.name}>
        {side.date} · {side.name}
      </span>
    </>
  );
}

// Likely transfers between the user's data sources. Nothing is linked until the user approves it,
// so no row starts ticked.
export default function Transfers() {
  const toast = useToast();
  const [data, setData] = useState<TransferSuggestions | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await apiFetch(SUGGESTIONS_URL);
        if (cancelled) return;
        if (res.ok) {
          setData(await res.json());
          setSelected(new Set());
        } else {
          setError(await readError(res, "Could not look for transfers."));
        }
      } catch {
        if (!cancelled) setError("Cannot reach the server.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  function toggle(key: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function approve() {
    const pairs = (data?.pairs ?? [])
      .filter((pair) => selected.has(keyOf(pair)))
      .map((pair) => ({ first: pair.debit.id, second: pair.credit.id }));
    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch(BULK_URL, { method: "POST", body: JSON.stringify({ pairs }) });
      if (!res.ok) {
        setError(await readError(res, "Could not link them."));
        return;
      }
      const body: { linked: number; failed: unknown[] } = await res.json();
      toast.success(`${body.linked} ${body.linked === 1 ? "transfer" : "transfers"} linked.`);
      if (body.failed.length) toast.error(`${body.failed.length} could not be linked. Their rows have changed.`);
      setReloadKey((key) => key + 1);
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setSaving(false);
    }
  }

  const pairs = data?.pairs ?? [];
  const allSelected = pairs.length > 0 && selected.size === pairs.length;

  return (
    <>
      <PageHeader
        title="Transfers"
        subtitle="Money moved between your own data sources shows as spend in one and income in the other. Link each pair, and charts that show both leave it out. Your balances don't change."
        actions={
          <Button variant="primary" disabled={selected.size === 0} loading={saving} onClick={approve}>
            Link {selected.size || ""} selected
          </Button>
        }
      />

      {error && <ErrorNote className="mb-4">{error}</ErrorNote>}
      {!data && !error && <Loading />}

      {data && pairs.length === 0 && (
        <EmptyState
          icon={<Link2 size={22} aria-hidden />}
          title="No likely transfers"
          action={
            <Link href="/transactions" className={buttonClass("secondary", "md")}>
              View transactions
            </Link>
          }
        >
          These show up when one data source has money going out and another has the same amount coming in, within 3
          days, in the last year. You can also link any transaction from the Transactions page.
        </EmptyState>
      )}

      {pairs.length > 0 && (
        <>
          {data && data.total > pairs.length && (
            <p className="mb-3 text-sm text-ink-2">
              Showing the newest {pairs.length} of {data.total}. Link these to see the rest.
            </p>
          )}
          <Table>
            <thead>
              <Tr className="hover:bg-transparent">
                <Th className="w-10">
                  <Checkbox
                    aria-label="Select all"
                    checked={allSelected}
                    onChange={(checked) => setSelected(new Set(checked ? pairs.map(keyOf) : []))}
                  />
                </Th>
                <Th>Money out of</Th>
                <Th>Money into</Th>
                <Th align="right">Amount</Th>
                <Th align="right">Days apart</Th>
              </Tr>
            </thead>
            <tbody>
              {pairs.map((pair) => {
                const key = keyOf(pair);
                return (
                  <Tr key={key}>
                    <Td className="w-10">
                      <Checkbox
                        aria-label={`Select ${pair.debit.name} to ${pair.credit.name}`}
                        checked={selected.has(key)}
                        onChange={(checked) => toggle(key, checked)}
                      />
                    </Td>
                    <Td>
                      <Side side={pair.debit} />
                    </Td>
                    <Td>
                      <Side side={pair.credit} />
                    </Td>
                    <Td align="right" className="whitespace-nowrap">
                      {money(pair.amount)}
                    </Td>
                    <Td align="right">{pair.days_apart}</Td>
                  </Tr>
                );
              })}
            </tbody>
          </Table>
        </>
      )}
    </>
  );
}
