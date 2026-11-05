"use client";

import { useState, type FormEvent } from "react";
import { LogOut, UserX } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { BIRTH_DATE_HINT, EARLIEST_BIRTH_DATE } from "@/lib/birthDate";
import { readError } from "@/lib/errors";
import { signOut } from "@/lib/signOut";
import { useSession } from "@/components/shell/Session";
import { DeleteAccountDialog } from "@/components/settings/DeleteAccountDialog";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorNote } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";

// MoneyAngle is for adults only. Accounts made before the date of birth was asked for see this in
// place of every app page until they give it (the server refuses everything else meanwhile, with
// accounts.permissions.AgeConfirmed). Leaving is always possible: log out, or delete the account.
export function AgeGate() {
  const { birthDateConfirmed } = useSession();
  const [birthDate, setBirthDate] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setFieldError(null);
    setError(null);
    try {
      const res = await apiFetch("/api/accounts/birth-date/", {
        method: "POST",
        body: JSON.stringify({ birth_date: birthDate }),
      });
      // 409: already on file (another tab got there first), so the app can open as well.
      if (res.ok || res.status === 409) {
        birthDateConfirmed();
        return;
      }
      const message = await readError(res, "Could not save your date of birth.");
      if (res.status === 400) setFieldError(message);
      else setError(message);
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-lg py-10">
      <Card>
        <h1 className="text-xl font-semibold tracking-tight">Confirm your date of birth</h1>
        <p className="mt-2 text-sm text-ink-2">
          MoneyAngle is for adults only. Your account was made before we asked, so please confirm your date of birth
          to continue.
        </p>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <Field label="Date of birth" error={fieldError} hint={BIRTH_DATE_HINT}>
            <Input
              type="date"
              autoComplete="bday"
              min={EARLIEST_BIRTH_DATE}
              value={birthDate}
              onChange={(e) => setBirthDate(e.target.value)}
              aria-invalid={!!fieldError}
              autoFocus
              required
            />
          </Field>
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button type="submit" variant="primary" loading={working} disabled={!birthDate} className="w-full">
            Continue
          </Button>
        </form>
        <div className="mt-6 flex flex-wrap gap-2 border-t-[1.5px] border-line pt-4">
          <Button variant="ghost" icon={<LogOut size={16} />} onClick={signOut}>
            Log out
          </Button>
          <Button variant="ghost" icon={<UserX size={16} />} onClick={() => setConfirmingDelete(true)}>
            Delete my account
          </Button>
        </div>
      </Card>
      <DeleteAccountDialog open={confirmingDelete} onClose={() => setConfirmingDelete(false)} />
    </div>
  );
}
