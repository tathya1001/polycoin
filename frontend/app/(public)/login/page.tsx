"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { ErrorNote } from "@/components/ui/Feedback";

const RECOVER_LINK = "font-semibold text-ink underline underline-offset-4";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The password no longer opens the data (409), or the account is locked after too many failed
  // attempts (429): both point to the recovery key.
  const [locked, setLocked] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLocked(false);
    setLoading(true);

    try {
      const res = await apiFetch("/api/accounts/login/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });

      if (res.ok) {
        router.push("/dashboard");
        return;
      }
      if (res.status === 401) setError("Invalid email or password.");
      else if (res.status === 429 || res.status === 409) {
        // Too many attempts: from this address (a minute) or on this account (an hour, with the
        // way out through the recovery key). Or a password set outside the app.
        const body = await res.clone().json().catch(() => null);
        setLocked(res.status === 409 || body?.code === "account_locked");
        setError(await readError(res, "Too many attempts. Wait a minute and try again."));
      } else setError("Something went wrong. Please try again.");
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Log in to see your dashboards."
      footer={
        <>
          No account?{" "}
          <Link href="/register" className={RECOVER_LINK}>
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Email">
          <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        {error && (
          <ErrorNote>
            {error}
            {locked && (
              <>
                {" "}
                <Link href="/recover" className={RECOVER_LINK}>
                  Use your recovery key
                </Link>
              </>
            )}
          </ErrorNote>
        )}
        <Button type="submit" variant="primary" loading={loading} className="w-full">
          {loading ? "Logging in…" : "Log in"}
        </Button>
        <p className="text-center text-sm text-ink-2">
          <Link href="/recover" className={RECOVER_LINK}>
            Forgot your password?
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}
