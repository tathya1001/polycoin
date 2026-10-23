"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { ErrorNote } from "@/components/ui/Feedback";

// DRF returns validation errors as { field: ["msg", ...] }; show each under its own field.
type FieldErrors = { email?: string; password?: string; other?: string };

function readFieldErrors(data: unknown): FieldErrors {
  if (typeof data !== "object" || data === null) return { other: "Registration failed." };
  const errors: FieldErrors = {};
  for (const [field, messages] of Object.entries(data as Record<string, unknown>)) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    if (field === "email" || field === "password") errors[field] = text;
    else errors.other = text;
  }
  return Object.keys(errors).length ? errors : { other: "Registration failed." };
}

export default function Register() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setLoading(true);

    try {
      const res = await apiFetch("/api/accounts/register/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
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

      // Registered. Log in right away so the user lands on the dashboard.
      const login = await apiFetch("/api/accounts/login/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.push(login.ok ? "/dashboard" : "/login");
    } catch {
      setErrors({ other: "Cannot reach the server." });
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Your data is encrypted with a key that only belongs to you."
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
        <Field label="Password" error={errors.password} hint="At least 8 characters, not too common.">
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
            required
          />
        </Field>
        {errors.other && <ErrorNote>{errors.other}</ErrorNote>}
        <Button type="submit" variant="primary" loading={loading} className="w-full">
          {loading ? "Creating…" : "Create account"}
        </Button>
        <p className="text-xs text-muted">
          Your statement data is encrypted at rest with a key unique to your account. The AI features are optional.
          The AI model runs on your computer: your browser sends transaction text to the Ollama you install, never to
          an AI service. The search index is stored encrypted on our server. You can delete all your data any time in
          Settings.
        </p>
      </form>
    </AuthLayout>
  );
}
