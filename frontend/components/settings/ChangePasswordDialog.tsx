"use client";

import { useId, useState, type FormEvent } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorNote } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";

type Errors = { current_password?: string; new_password?: string; other?: string };

const text = (value: unknown) => (Array.isArray(value) ? value.join(" ") : String(value));

// Phase 12.1, D12: the data key is re-locked with the new password, every other device is signed
// out, and the recovery key stays the same.
export function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const formId = useId();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [working, setWorking] = useState(false);

  function close() {
    if (working) return;
    setCurrent("");
    setNext("");
    setErrors({});
    onClose();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setErrors({});
    try {
      const res = await apiFetch("/api/accounts/change-password/", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      if (res.ok) {
        toast.success("Password changed. Your other devices were signed out.");
        setWorking(false);
        setCurrent("");
        setNext("");
        onClose();
        return;
      }
      const body = res.status === 400 ? await res.clone().json().catch(() => null) : null;
      if (body?.current_password || body?.new_password) {
        setErrors({
          current_password: body.current_password && text(body.current_password),
          new_password: body.new_password && text(body.new_password),
        });
      } else setErrors({ other: await readError(res, "Could not change your password.") });
    } catch {
      setErrors({ other: "Cannot reach the server." });
    } finally {
      setWorking(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Change your password"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={working}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={working} disabled={!current || !next}>
            Change password
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="space-y-4">
        <p className="text-sm text-ink-2">
          Your data is re-locked with the new password. Other devices are signed out; this one stays signed in. Your
          recovery key doesn&apos;t change.
        </p>
        <Field label="Current password" error={errors.current_password}>
          <Input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            aria-invalid={!!errors.current_password}
            autoFocus
            required
          />
        </Field>
        <Field label="New password" error={errors.new_password} hint="At least 8 characters, not too common.">
          <Input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            aria-invalid={!!errors.new_password}
            required
          />
        </Field>
        {errors.other && <ErrorNote>{errors.other}</ErrorNote>}
      </form>
    </Dialog>
  );
}
