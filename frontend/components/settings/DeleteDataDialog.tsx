"use client";

import { useState, type FormEvent } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { forgetAll } from "@/lib/storage";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { ErrorNote } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toast";

type Erased = { transactions: number; dashboards: number; categories: number };

const FORM_ID = "delete-data-form";

// "Delete all my data": explains exactly what goes and what stays, then asks for the account
// password again (a stolen session must not be able to wipe an account). The server does the
// real checking; this only collects the password and shows the result.
export function DeleteDataDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  function close() {
    if (working) return; // never walk away from a request that is in flight
    setPassword("");
    setFieldError(null);
    setError(null);
    onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setFieldError(null);
    setError(null);
    try {
      const res = await apiFetch("/api/accounts/delete-data/", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      if (res.ok) {
        const erased: Erased = await res.json();
        forgetAll("polycoin.dashboard."); // the open tab and filters point at dashboards that are gone
        setPassword("");
        toast.success(
          `All your data was deleted: ${erased.transactions} transactions and ${erased.dashboards} dashboards.`,
        );
        onClose();
        return;
      }
      const message = await readError(res, "Could not delete your data.");
      if (res.status === 400) setFieldError(message); // "Incorrect password."
      else setError(message);
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Delete all your data?"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={working}>
            Cancel
          </Button>
          <Button type="submit" form={FORM_ID} variant="danger" loading={working} disabled={!password}>
            Delete everything
          </Button>
        </>
      }
    >
      <form id={FORM_ID} onSubmit={submit} className="space-y-4">
        <div className="space-y-2 text-sm">
          <p className="font-medium">This cannot be undone. It deletes:</p>
          <ul className="list-disc space-y-0.5 pl-5 text-ink-2">
            <li>every transaction you imported</li>
            <li>every dashboard and panel</li>
            <li>your own categories and keywords (the starter categories come back)</li>
          </ul>
          <p className="text-ink-2">
            Your account, login and settings stay, so you can import a statement again right away.
          </p>
          <p className="text-ink-2">
            To keep a copy, download a Data Backup File first: you can restore it here later.
          </p>
        </div>
        <Field label="Enter your password to confirm" error={fieldError}>
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!fieldError}
            autoFocus
            required
          />
        </Field>
        {error && <ErrorNote>{error}</ErrorNote>}
      </form>
    </Dialog>
  );
}
