// The Data Backup File: everything the user has, as one file that only their own account can
// open. The server builds it and encrypts it with the account's key; this side only downloads
// it and uploads it back (backend/backups).

import { apiFetch } from "@/lib/api";
import { problemFrom, RagProblem } from "@/lib/rag";

const BACKUP_URL = "/api/backup/";
const RESTORE_URL = "/api/backup/restore/";
export const BACKUP_EXTENSION = ".polycoin";
export const MAX_BACKUP_BYTES = 4 * 1024 * 1024; // the server's BACKUP_MAX_BYTES

// The server's {code, detail} refusals, as elsewhere.
export { RagProblem as BackupProblem };

export type RestoreCounts = {
  transactions: { added: number; skipped: number };
  categories: { added: number };
  keywords: { added: number };
  dashboards: { added: number; skipped: number };
  panels_skipped: number;
};

const SAFE_NAME = /^[\w.-]{1,100}$/;

/** The file name the server sent, or a dated default. Only a plain name is accepted. */
export function fileNameFrom(disposition: string | null, today: Date): string {
  const sent = disposition?.match(/filename="([^"]+)"/)?.[1];
  if (sent && SAFE_NAME.test(sent)) return sent;
  const day = today.toISOString().slice(0, 10);
  return `backup-${day}${BACKUP_EXTENSION}`;
}

export async function fetchBackup(): Promise<{ name: string; blob: Blob }> {
  const res = await apiFetch(BACKUP_URL);
  if (!res.ok) throw await problemFrom(res);
  return { name: fileNameFrom(res.headers.get("Content-Disposition"), new Date()), blob: await res.blob() };
}

/** Hands a downloaded file to the browser's own "save" flow. */
export function saveFile(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0); // after the click has started the download
}

export async function restoreBackup(file: File): Promise<RestoreCounts> {
  if (file.size > MAX_BACKUP_BYTES) {
    throw new RagProblem("too_large", "A backup file can be at most 4 MB.", 0); // don't upload it
  }
  const body = new FormData();
  body.append("file", file);
  const res = await apiFetch(RESTORE_URL, { method: "POST", body });
  if (!res.ok) throw await problemFrom(res);
  return res.json();
}

function count(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** One sentence for the result: what was added, and what was already there. */
export function restoreSummary(counts: RestoreCounts): string {
  const added = [
    count(counts.transactions.added, "transaction", "transactions"),
    count(counts.categories.added, "category", "categories"),
    count(counts.dashboards.added, "dashboard", "dashboards"),
  ];
  const already = counts.transactions.skipped + counts.dashboards.skipped;
  let text = `Restored ${added.join(", ")}.`;
  if (already) text += ` ${count(already, "item was", "items were")} already there.`;
  if (counts.panels_skipped) {
    text += ` ${count(counts.panels_skipped, "panel", "panels")} could not be restored.`;
  }
  return text;
}
