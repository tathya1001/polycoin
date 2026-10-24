"use client";

import PanelBody from "@/components/charts/PanelBody";
import type { CategoryColors } from "@/components/charts/toOption";
import { Chip } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import type { AgentOutcome } from "@/lib/types";

export const MAX_TITLE = 80; // the server's limit on a panel title

type Preview = Extract<AgentOutcome, { kind: "preview" }>;

// The panel the AI built, drawn exactly as the dashboard will draw it, with a title the user
// can change and the server's notes on what it changed or could not match. The title and notes
// are text the model or the server wrote, so they are only ever shown as text.
export default function AgentPreview({
  preview,
  title,
  onTitle,
  categoryColors,
}: {
  preview: Preview;
  title: string;
  onTitle: (title: string) => void;
  categoryColors: CategoryColors;
}) {
  return (
    <div className="space-y-3">
      <Field label="Title" hint={preview.summary}>
        <Input value={title} maxLength={MAX_TITLE} onChange={(e) => onTitle(e.target.value)} />
      </Field>
      <div className="h-64 rounded-md border-[1.5px] border-ink bg-surface p-2 shadow-hard-sm">
        <PanelBody config={preview.config} outcome={preview.result} loading={false} categoryColors={categoryColors} />
      </div>
      {preview.notes.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Notes">
          {preview.notes.map((note, index) => (
            <li key={index}>
              <Chip className="h-auto min-h-8 py-1 whitespace-normal">{note}</Chip>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
