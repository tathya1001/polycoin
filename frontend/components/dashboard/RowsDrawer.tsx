"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorNote, Loading } from "@/components/ui/Feedback";
import { MoneyCell, Table, Td, Th, Tr } from "@/components/ui/Table";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { ROWS_URL, formatValue } from "@/lib/insights";
import { money } from "@/lib/format";
import type { DashboardParameters, PanelConfig, PanelFilters, RowsPage, Selection } from "@/lib/types";

export type RowsRequest = {
  filters: PanelFilters; // the dashboard's filter bar
  parameters?: DashboardParameters;
  config: PanelConfig; // the panel as it is drawn now, drill-down included
  mark: Selection; // what was clicked; empty for a whole panel
  selection?: Selection; // a click on another panel that is filtering this one
};

const PAGE_SIZE = 50;

// The transactions behind a number or a mark, in a dialog. Opened on demand, so nothing
// is decrypted until the user asks.
export default function RowsDrawer({ title, request, onClose }: { title: string; request: RowsRequest; onClose: () => void }) {
  const [page, setPage] = useState<RowsPage | null>(null);
  const [rows, setRows] = useState<RowsPage["rows"]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [more, setMore] = useState(0); // how many times "Show more" was pressed

  useEffect(() => {
    let cancelled = false; // closed, or asked again, before the answer came
    async function load() {
      setBusy(true);
      try {
        const res = await apiFetch(ROWS_URL, {
          method: "POST",
          body: JSON.stringify({
            filters: request.filters,
            ...(request.parameters ? { parameters: request.parameters } : {}),
            spec: request.config,
            mark: request.mark,
            ...(request.selection ? { selection: request.selection } : {}),
            offset: more * PAGE_SIZE,
            limit: PAGE_SIZE,
          }),
        });
        if (cancelled) return;
        if (!res.ok) return setError(await readError(res, "Could not load the transactions."));
        const body: RowsPage = await res.json();
        if (cancelled) return;
        setError(null);
        setPage(body);
        setRows((shown) => (more === 0 ? body.rows : [...shown, ...body.rows]));
      } catch {
        if (!cancelled) setError("Cannot reach the server.");
      } finally {
        if (!cancelled) setBusy(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [request, more]);

  const manySources = new Set(rows.map((row) => row.data_source)).size > 1;

  return (
    <Dialog open onClose={onClose} title={title || "Transactions"} size="lg">
      {error && <ErrorNote>{error}</ErrorNote>}
      {!page && !error && <Loading />}
      {page && (
        <div className="space-y-3 pb-3">
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-2">
            <span>
              <strong className="font-semibold text-ink">{page.total.toLocaleString("en-IN")}</strong>{" "}
              {page.total === 1 ? "transaction" : "transactions"}
            </span>
            <span>
              {/* The value is the measure itself; a table calculation changes what the bar shows. */}
              {request.config.calc ? "Before the calculation" : "The chart shows"}{" "}
              <strong className="font-semibold text-ink">
                {formatValue(page.value, { ...request.config, calc: undefined })}
              </strong>
            </span>
            <span>
              {page.period.from} to {page.period.to}
            </span>
          </p>
          {page.total === 0 ? (
            <p className="py-6 text-center text-ink-2">No transactions here.</p>
          ) : (
            <Table>
              <thead>
                <Tr>
                  <Th>Date</Th>
                  <Th>Name</Th>
                  <Th>Category</Th>
                  {manySources && <Th>Data source</Th>}
                  <Th align="right">Amount</Th>
                </Tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <Tr key={index}>
                    <Td className="whitespace-nowrap">{row.date}</Td>
                    <Td className="max-w-56 truncate" title={row.name}>
                      {row.name}
                    </Td>
                    <Td>{row.category}</Td>
                    {manySources && <Td>{row.data_source}</Td>}
                    <MoneyCell value={row.amount} type={row.txn_type} />
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
          {page.total > 0 && (
            <p className="flex flex-wrap gap-x-4 text-sm text-ink-2">
              {Number(page.totals.debit) > 0 && <span>Money out {money(page.totals.debit)}</span>}
              {Number(page.totals.credit) > 0 && <span>Money in {money(page.totals.credit)}</span>}
            </p>
          )}
          {rows.length < page.total && (
            <div className="flex justify-center">
              <Button size="sm" disabled={busy} onClick={() => setMore((n) => n + 1)}>
                {busy ? "Loading…" : `Show more (${page.total - rows.length} left)`}
              </Button>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
