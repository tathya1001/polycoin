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

const RECOVER_LINK = "font-semibold text-ink underline underline-offset-4";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false); // the password no longer opens the data (409)
  const [loading, setLoading] = useState(false);
  // An account made before passwords locked the data switches over at this login and gets its
  // recovery key, shown once, before anything else.
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null);

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
        const body = await res.json();
        if (body.recovery_key) setRecoveryKey(body.recovery_key);
        else router.push("/dashboard");
        return;
      }
      if (res.status === 401) setError("Invalid email or password.");
      else if (res.status === 429) setError("Too many attempts. Wait a minute and try again.");
      else if (res.status === 409) {
        setLocked(true);
        setError(await readError(res, "Your data is locked with an earlier password."));
      } else if (res.status === 503) setError(await readError(res, "Your data can't be unlocked right now."));
      else setError("Something went wrong. Please try again.");
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setLoading(false);
    }
  }

  if (recoveryKey) {
    return (
      <AuthLayout
        title="Save your recovery key"
        subtitle="Your data is now locked with your password."
        footer={null}
      >
        <RecoveryKeyPanel
          recoveryKey={recoveryKey}
          intro="MoneyAngle now locks your data with your password, so nobody can open it without you. If you ever forget the password, this key is the only way to set a new one."
          continueLabel="Go to my dashboard"
          onContinue={() => router.push("/dashboard")}
        />
      </AuthLayout>
    );
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
