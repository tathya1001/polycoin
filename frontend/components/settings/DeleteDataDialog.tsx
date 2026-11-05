"use client";

import { forgetAll } from "@/lib/storage";
import { PasswordConfirmDialog } from "@/components/settings/PasswordConfirmDialog";
import { useToast } from "@/components/ui/Toast";

type Erased = { transactions: number; dashboards: number; categories: number };

// "Delete all my data": explains exactly what goes and what stays, then asks for the password.
export function DeleteDataDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();

  async function done(res: Response) {
    const erased: Erased = await res.json();
    forgetAll("moneyangle.dashboard."); // the open tab and filters point at dashboards that are gone
    toast.success(`All your data was deleted: ${erased.transactions} transactions and ${erased.dashboards} dashboards.`);
    onClose();
  }

  return (
    <PasswordConfirmDialog
      open={open}
      onClose={onClose}
      title="Delete all your data?"
      url="/api/accounts/delete-data/"
      confirmLabel="Delete everything"
      failure="Could not delete your data."
      onDone={done}
    >
      <p className="font-medium">This cannot be undone. It deletes:</p>
      <ul className="list-disc space-y-0.5 pl-5 text-ink-2">
        <li>every transaction you imported</li>
        <li>every dashboard and panel</li>
        <li>your own categories and keywords (the starter categories come back)</li>
      </ul>
      <p className="text-ink-2">Your account, login and settings stay, so you can import a statement again right away.</p>
      <p className="text-ink-2">To keep a copy, download a Data Backup File first: you can restore it here later.</p>
    </PasswordConfirmDialog>
  );
}
