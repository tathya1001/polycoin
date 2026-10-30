"use client";

import { useEffect, useState } from "react";
import { Link2, Unlink } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { sourceName } from "@/lib/dataSources";
import { readError } from "@/lib/errors";
import { money } from "@/lib/format";
import type { DataSource, LinkCandidate, Transaction } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, ErrorNote, Loading } from "@/components/ui/Feedback";
import { Field, Select } from "@/components/ui/Field";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";

const LINKS_URL = "/api/transactions/links/";
const WINDOWS = [7, 14, 31]; // transactions.links.MAX_CANDIDATE_DAYS is the last

type Props = {
  transaction: Transaction;
  sources: DataSource[];
  onClose: () => void;
  onChanged: () => void; // a link was made or removed
};

// Links one transaction to the other side of a transfer, or undoes a link. Stays on the
// transactions page, so the user keeps their place in the list.
export default function LinkDialog({ transaction, sources, onClose, onChanged }: Props) {
  const toast = useToast();
  const [days, setDays] = useState(WINDOWS[0]);
  const [candidates, setCandidates] = useState<LinkCandidate[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const link = transaction.link;

  useEffect(() => {
    if (link) return;
    let cancelled = false;
    async function load() {
      setCandidates(null);
      try {
        const res = await apiFetch(`/api/transactions/${transaction.id}/link-candidates/?days=${days}`);
        if (cancelled) return;
        if (res.ok) setCandidates(await res.json());
        else setError(await readError(res, "Could not look for matches."));
      } catch {
        if (!cancelled) setError("Cannot reach the server.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [transaction.id, link, days]);

  async function save(partner: string) {
    setBusy(partner);
    setError(null);
    try {
      const res = await apiFetch(LINKS_URL, {
        method: "POST",
        body: JSON.stringify({ first: transaction.id, second: partner }),
      });
      if (res.ok) {
        toast.success("Linked as a transfer.");
        onChanged();
      } else {
        setError(await readError(res, "Could not link them."));
      }
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setBusy(null);
    }
  }

  async function unlink() {
    if (!link) return;
    setBusy(link.id);
    setError(null);
    try {
      const res = await apiFetch(`${LINKS_URL}${link.id}/`, { method: "DELETE" });
      if (res.ok) {
        toast.success("Link removed.");
        onChanged();
      } else {
        setError(await readError(res, "Could not remove the link."));
      }
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open onClose={onClose} title="Link as a transfer" size="md">
      <div className="space-y-3 pb-3 text-sm">
        <p>
          <strong className="font-semibold">{transaction.name}</strong>, {transaction.date},{" "}
          {money(transaction.amount)} {transaction.txn_type === "debit" ? "out of" : "into"}{" "}
          {sourceName(transaction.data_source, sources)}.
        </p>
        <p className="text-ink-2">
          A linked pair is one movement of your own money. Charts that show both data sources leave both rows out of
          spend and income. Balances don&apos;t change.
        </p>
        {error && <ErrorNote>{error}</ErrorNote>}

        {link ? (
          <div className="space-y-3">
            <p>Linked to a transaction in {sourceName(link.partner_source, sources)}.</p>
            <Button icon={<Unlink size={15} />} loading={busy === link.id} onClick={unlink}>
              Remove the link
            </Button>
          </div>
        ) : (
          <>
            <Field label="Look within" className="w-40">
              <Select dense className="w-full" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {WINDOWS.map((window) => (
                  <option key={window} value={window}>
                    {window} days
                  </option>
                ))}
              </Select>
            </Field>
            {candidates === null ? (
              <Loading />
            ) : candidates.length === 0 ? (
              <EmptyState icon={<Link2 size={22} aria-hidden />} title="No match found">
                Nothing with the same amount, going the other way, in another data source.
              </EmptyState>
            ) : (
              <Table>
                <thead>
                  <Tr>
                    <Th>Date</Th>
                    <Th>Name</Th>
                    <Th>Data source</Th>
                    <Th>
                      <span className="sr-only">Link</span>
                    </Th>
                  </Tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => (
                    <Tr key={candidate.id}>
                      <Td className="whitespace-nowrap">{candidate.date}</Td>
                      <Td className="max-w-48 truncate" title={candidate.name}>
                        {candidate.name}
                      </Td>
                      <Td>{candidate.data_source_name}</Td>
                      <Td>
                        <Button size="sm" loading={busy === candidate.id} onClick={() => save(candidate.id)}>
                          Link
                        </Button>
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
