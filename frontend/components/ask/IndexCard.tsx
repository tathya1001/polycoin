"use client";

import { RefreshCw, Trash2 } from "lucide-react";
import type { SyncProgress } from "@/lib/rag";
import type { RagStatus } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Badge, Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Feedback";

// How much of the user's history is searchable with the chosen model, and the controls that change it.
export function IndexCard({
  status,
  syncing,
  progress,
  clearing,
  onUpdate,
  onClear,
}: {
  status: RagStatus;
  syncing: boolean;
  progress: SyncProgress | null;
  clearing: boolean;
  onUpdate: () => void;
  onClear: () => void;
}) {
  const complete = status.indexed >= status.total;
  return (
    <Card className="mb-5 flex flex-wrap items-center justify-between gap-3 p-4!">
      <div className="space-y-1 text-sm">
        <p>
          <strong>{status.indexed.toLocaleString("en-IN")}</strong> of{" "}
          <strong>{status.total.toLocaleString("en-IN")}</strong> transactions indexed
          {complete && status.total > 0 && " (up to date)"}
        </p>
        {syncing && (
          <p role="status" className="flex items-center gap-2 text-ink-2">
            <Spinner size={14} />
            {progress
              ? `Indexing on your computer: ${progress.stored.toLocaleString("en-IN")} done, ${progress.remaining.toLocaleString("en-IN")} to go…`
              : "Checking what needs indexing…"}
          </p>
        )}
        {!status.profile.tuned && (
          <Badge tone="warn">Untuned model: answers may include loosely related transactions</Badge>
        )}
      </div>
      <div className="flex gap-2">
        <Button size="sm" loading={syncing} icon={<RefreshCw size={14} />} disabled={complete || clearing} onClick={onUpdate}>
          Update
        </Button>
        <Button
          size="sm"
          variant="ghost"
          loading={clearing}
          icon={<Trash2 size={14} />}
          disabled={syncing || status.indexed === 0}
          onClick={onClear}
        >
          Clear index
        </Button>
      </div>
    </Card>
  );
}
