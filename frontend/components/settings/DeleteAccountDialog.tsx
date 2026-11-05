"use client";

import { leave } from "@/lib/signOut";
import { PasswordConfirmDialog } from "@/components/settings/PasswordConfirmDialog";

// "Delete my account": everything goes, the account included, and this browser forgets it too.
export function DeleteAccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <PasswordConfirmDialog
      open={open}
      onClose={onClose}
      title="Delete your account?"
      url="/api/accounts/delete-account/"
      confirmLabel="Delete my account"
      failure="Could not delete your account."
      onDone={() => leave("/?account=deleted")}
    >
      <p className="font-medium">This cannot be undone. It permanently deletes:</p>
      <ul className="list-disc space-y-0.5 pl-5 text-ink-2">
        <li>your account, email address and password</li>
        <li>every transaction, dashboard, category and data source</li>
        <li>your settings, and the key your data was encrypted with</li>
      </ul>
      <p className="text-ink-2">
        Without that key, Data Backup Files you downloaded can never be opened again, here or anywhere.
      </p>
      <p className="text-ink-2">You will be signed out. You can sign up again later with the same email, as a new account.</p>
    </PasswordConfirmDialog>
  );
}
