"use client";

import { Fragment } from "react";
import { parseCitations } from "@/lib/rag";
import type { RagSource } from "@/lib/types";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Feedback";

// The model's answer, rendered as plain text only: it is untrusted output (a UPI note can carry
// text the model repeats). No HTML, no markdown, no links built from its words. Each valid [n]
// becomes a chip that jumps to row n of the sources table.
export function AnswerView({
  answer,
  sources,
  inPrompt,
  streaming,
  onCite,
}: {
  answer: string;
  sources: RagSource[];
  inPrompt: number;
  streaming: boolean;
  onCite: (n: number) => void;
}) {
  const segments = parseCitations(answer, sources, inPrompt);
  return (
    <Card className="mb-4">
      {answer === "" && streaming ? (
        <p role="status" className="flex items-center gap-2 text-ink-2">
          <Spinner size={16} />
          Writing the answer on your computer…
        </p>
      ) : (
        <p className="leading-relaxed whitespace-pre-wrap" aria-live="polite" aria-busy={streaming}>
          {segments.map((segment, index) =>
            segment.kind === "text" ? (
              <Fragment key={index}>{segment.text}</Fragment>
            ) : (
              <button
                key={index}
                type="button"
                onClick={() => onCite(segment.source.n)}
                title={`${segment.source.name}, ${segment.source.date}`}
                className="mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-full border-[1.5px] border-ink bg-surface px-1 align-[0.1em] text-[11px] font-semibold hover:bg-wash"
              >
                {segment.source.n}
              </button>
            ),
          )}
          {streaming && <span aria-hidden className="ml-0.5 animate-pulse">▍</span>}
        </p>
      )}
    </Card>
  );
}
