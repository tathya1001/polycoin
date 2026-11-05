"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { RecoveryKeyPanel } from "@/components/auth/RecoveryKeyPanel";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { ErrorNote } from "@/components/ui/Feedback";
import { BIRTH_DATE_HINT, EARLIEST_BIRTH_DATE } from "@/lib/birthDate";

// DRF returns validation errors as { field: ["msg", ...] }; show each under its own field.
type FieldErrors = { email?: string; password?: string; birth_date?: string; other?: string };
const FIELDS = ["email", "password", "birth_date"] as const;

function readFieldErrors(data: unknown): FieldErrors {
  if (typeof data !== "object" || data === null) return { other: "Registration failed." };
  const errors: FieldErrors = {};
  for (const [field, messages] of Object.entries(data as Record<string, unknown>)) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    if ((FIELDS as readonly string[]).includes(field)) errors[field as (typeof FIELDS)[number]] = text;
    else errors.other = text;
  }
  return Object.keys(errors).length ? errors : { other: "Registration failed." };
}

export default function Register() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [birthDate, setBirthDate] = useState(""); // YYYY-MM-DD, from the date input
  const [errors, setErrors] = useState<FieldErrors>({});
  const [loading, setLoading] = useState(false);
  // Set once the account exists: shown before anything else happens (it is shown only once).
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null);

  async function logInAndGo() {
    setLoading(true);
    try {
      const login = await apiFetch("/api/accounts/login/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.push(login.ok ? "/dashboard" : "/login");
    } catch {
      router.push("/login");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setLoading(true);

    try {
      const res = await apiFetch("/api/accounts/register/", {
        method: "POST",
        body: JSON.stringify({ email, password, birth_date: birthDate }),
      });

      if (res.status === 429) {
        setErrors({ other: "Too many attempts. Wait a minute and try again." });
        return;
      }
      // A server error sends an HTML page, not JSON: say so instead of blaming the network.
      if (res.status >= 500) {
        setErrors({ other: "Something went wrong on our side. Please try again later." });
        return;
      }
      if (!res.ok) {
        setErrors(readFieldErrors(await res.json().catch(() => null)));
        return;
      }

      // Registered. The recovery key comes first; logging in waits until it is saved.
      setRecoveryKey((await res.json()).recovery_key);
    } catch {
      setErrors({ other: "Cannot reach the server." });
    } finally {
      setLoading(false);
    }
  }

  if (recoveryKey) {
    return (
      <AuthLayout title="Save your recovery key" subtitle="Your account is ready. One last, important step." footer={null}>
        <RecoveryKeyPanel
          recoveryKey={recoveryKey}
          intro="Your data is locked with your password. If you ever forget it, this key is the only way to set a new one."
          continueLabel={loading ? "Opening your account…" : "Go to my dashboard"}
          onContinue={logInAndGo}
        />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Your data is locked with a key only your password can open."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-ink underline underline-offset-4">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Email" error={errors.email}>
          <Input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!errors.email}
            required
          />
        </Field>
        <Field label="Password" error={errors.password} hint="At least 12 characters, not too common. A short sentence works well.">
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
            required
          />
        </Field>
        <Field label="Date of birth" error={errors.birth_date} hint={BIRTH_DATE_HINT}>
          <Input
            type="date"
            autoComplete="bday"
            min={EARLIEST_BIRTH_DATE}
            value={birthDate}
            onChange={(e) => setBirthDate(e.target.value)}
            aria-invalid={!!errors.birth_date}
            required
          />
        </Field>
        {errors.other && <ErrorNote>{errors.other}</ErrorNote>}
        <Button type="submit" variant="primary" loading={loading} className="w-full">
          {loading ? "Creating…" : "Create account"}
        </Button>
        <p className="text-xs text-muted">
          Your statement data is stored encrypted, with a key locked by your password. Without your password or your
          recovery key, nobody can read it, us included. While you are signed in, our server unlocks it to build your
          dashboards; logging out locks it again. We can&apos;t reset your password: you&apos;ll get a recovery key to
          keep. The AI features are optional and run on your computer: your browser sends transaction text to the
          Ollama you install, never to an AI service. You can delete all your data, or your whole account, any time in
          Settings.
        </p>
      </form>
    </AuthLayout>
  );
}
