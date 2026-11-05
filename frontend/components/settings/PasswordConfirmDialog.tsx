"use client";

import { useId, useState, type FormEvent, type ReactNode } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { ErrorNote } from "@/components/ui/Feedback";

// A destructive action that asks for the account password again: a stolen session, or a stranger
// at an unlocked laptop, must not be able to wipe anything. The server does the real checking;
// this only explains what will happen (`children`), collects the password, posts it to `url`, and
// hands a successful response to `onDone`.
export function PasswordConfirmDialog({
  open,
  onClose,
  title,
  url,
  confirmLabel,
  failure,
  onDone,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  url: string;
  confirmLabel: string;
  failure: string; // shown when the server refuses for a reason other than the password
  onDone: (res: Response) => void | Promise<void>;
  children: ReactNode;
}) {
  const formId = useId();
  const [password, setPassword] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  function reset() {
    setPassword("");
    setFieldError(null);
    setError(null);
  }

  function close() {
    if (working) return; // never walk away from a request that is in flight
    reset();
    onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setFieldError(null);
    setError(null);
    try {
      const res = await apiFetch(url, { method: "POST", body: JSON.stringify({ password }) });
      if (res.ok) {
        reset();
        await onDone(res);
        return;
      }
      const message = await readError(res, failure);
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
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={working}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="danger" loading={working} disabled={!password}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="space-y-4">
        <div className="space-y-2 text-sm">{children}</div>
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
