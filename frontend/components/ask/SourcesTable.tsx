"use client";

import { cn } from "@/lib/cn";
import type { RagSource } from "@/lib/types";
import { MoneyCell, Table, Td, Th, Tr } from "@/components/ui/Table";

export const sourceRowId = (n: number) => `source-${n}`;

// Every matching transaction, numbered as the answer cites them. Drawn from the server's data,
// never from the model's words, so a made-up amount can't appear here.
export function SourcesTable({ sources, highlighted }: { sources: RagSource[]; highlighted: number | null }) {
  return (
    <Table>
      <thead>
        <Tr className="hover:bg-transparent">
          <Th align="right">#</Th>
          <Th>Date</Th>
          <Th>Name</Th>
          <Th>Category</Th>
          <Th align="right">Amount</Th>
        </Tr>
      </thead>
      <tbody>
        {sources.map((source) => (
          <Tr
            key={source.transaction}
            id={sourceRowId(source.n)}
            className={cn("scroll-mt-24", highlighted === source.n && "bg-warn-bg hover:bg-warn-bg")}
          >
            <Td align="right" className="text-ink-2">
              {source.n}
            </Td>
            <Td className="whitespace-nowrap text-ink-2">{source.date}</Td>
            <Td className="font-medium">{source.name}</Td>
            <Td>
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="size-2.5 rounded-full" style={{ backgroundColor: source.category.color }} />
                {source.category.name}
              </span>
            </Td>
            <MoneyCell value={source.amount} type={source.txn_type} />
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}
