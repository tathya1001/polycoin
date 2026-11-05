"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { RecoveryKeyPanel } from "@/components/auth/RecoveryKeyPanel";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { ErrorNote } from "@/components/ui/Feedback";

// Forgot password (Phase 12.1, D13). Nobody can reset a password without the recovery key: the
// data is locked with the password, and the server never holds anything else that opens it.
export default function Recover() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [recoveryKey, setRecoveryKey] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // The recovery key just used is spent: the server sends a new one, shown once.
  const [newKey, setNewKey] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPasswordError(null);
    setLoading(true);
    try {
      const res = await apiFetch("/api/accounts/recover/", {
        method: "POST",
        body: JSON.stringify({ email, recovery_key: recoveryKey, new_password: newPassword }),
      });
      if (res.ok) {
        setNewKey((await res.json()).recovery_key);
        return;
      }
      if (res.status === 429) {
        setError("Too many attempts. Wait a minute and try again.");
        return;
      }
      const body = await res.clone().json().catch(() => null);
      if (body?.new_password) setPasswordError([body.new_password].flat().join(" "));
      else setError(await readError(res, "Could not recover your account."));
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setLoading(false);
    }
  }

  async function logInAndGo() {
    setLoading(true);
    try {
      const login = await apiFetch("/api/accounts/login/", {
        method: "POST",
        body: JSON.stringify({ email, password: newPassword }),
      });
      router.push(login.ok ? "/dashboard" : "/login");
    } catch {
      router.push("/login");
    }
  }

  if (newKey) {
    return (
      <AuthLayout title="Save your new recovery key" subtitle="Your password is changed." footer={null}>
        <RecoveryKeyPanel
          recoveryKey={newKey}
          intro="The recovery key you just used no longer works. This new one replaces it. Every other device was signed out."
          continueLabel={loading ? "Opening your account…" : "Go to my dashboard"}
          onContinue={logInAndGo}
        />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Forgot your password?"
      subtitle="Use the recovery key you saved when you signed up."
      footer={
        <>
          Remembered it?{" "}
          <Link href="/login" className="font-semibold text-ink underline underline-offset-4">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Email">
          <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Recovery key" hint="Eight groups of four letters and digits, like ABCD-EFGH-…">
          <Input
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            value={recoveryKey}
            onChange={(e) => setRecoveryKey(e.target.value)}
            required
          />
        </Field>
        <Field label="New password" error={passwordError} hint="At least 12 characters, not too common. A short sentence works well.">
          <Input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            aria-invalid={!!passwordError}
            required
          />
        </Field>
        {error && <ErrorNote>{error}</ErrorNote>}
        <Button type="submit" variant="primary" loading={loading} className="w-full">
          Set a new password
        </Button>
        <p className="text-xs text-muted">
          Without the recovery key, nobody can open your data, us included, so we can&apos;t reset your password for
          you. If you have lost both your password and your recovery key, your data can&apos;t be recovered.
        </p>
      </form>
    </AuthLayout>
  );
}
