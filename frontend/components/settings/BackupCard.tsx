"use client";

import { useRef, useState, type ChangeEvent } from "react";
import { Download, Upload } from "lucide-react";
import {
  BACKUP_EXTENSION,
  BackupProblem,
  fetchBackup,
  restoreBackup,
  restoreSummary,
  saveFile,
} from "@/lib/backup";
import { useSession } from "@/components/shell/Session";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorNote } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";

function explain(problem: unknown, fallback: string): string {
  if (problem instanceof BackupProblem) return problem.message;
  if (problem instanceof TypeError) return "Cannot reach the server.";
  return fallback;
}

// Download everything as one Data Backup File, or merge one back in. The server makes and reads
// the file; this card only moves it between the browser and the server.
export function BackupCard() {
  const toast = useToast();
  const { reloadPreferences } = useSession();
  const picker = useRef<HTMLInputElement>(null);
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setDownloading(true);
    setError(null);
    try {
      const { name, blob } = await fetchBackup();
      saveFile(name, blob);
    } catch (problem) {
      setError(explain(problem, "Could not make the backup file."));
    } finally {
      setDownloading(false);
    }
  }

  async function restore(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // the same file can be picked again
    if (!file) return;
    setRestoring(true);
    setError(null);
    try {
      const counts = await restoreBackup(file);
      await reloadPreferences(); // the file may hold another font or chart setting
      const ask = counts.transactions.added ? " Open Ask to update its search index." : "";
      toast.success(restoreSummary(counts) + ask);
    } catch (problem) {
      setError(explain(problem, "Could not restore the backup file."));
    } finally {
      setRestoring(false);
    }
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-xl">
          <p className="font-medium">Data Backup File</p>
          <p className="text-sm text-ink-2">
            Your transactions, notes, categories, dashboards and settings in one encrypted file. Only your
            Polycoin account can open it, so keep it somewhere safe. Restoring adds only what is missing, even
            after you delete your data.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button icon={<Download size={16} />} onClick={download} loading={downloading} disabled={restoring}>
            Download backup
          </Button>
          <Button
            icon={<Upload size={16} />}
            onClick={() => picker.current?.click()}
            loading={restoring}
            disabled={downloading}
          >
            Restore from backup
          </Button>
          <input
            ref={picker}
            type="file"
            accept={BACKUP_EXTENSION}
            className="hidden"
            aria-label="Backup file to restore"
            onChange={restore}
          />
        </div>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
    </Card>
  );
}
