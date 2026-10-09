"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";

// DRF returns validation errors as { field: ["msg", ...] }
function flattenErrors(data: unknown): string {
  if (typeof data !== "object" || data === null) return "Registration failed.";
  return Object.entries(data as Record<string, unknown>)
    .map(([field, msgs]) =>
      `${field}: ${Array.isArray(msgs) ? msgs.join(" ") : String(msgs)}`,
    )
    .join(" | ");
}

export default function Register() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await apiFetch("/api/accounts/register/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });

      if (res.status === 429) {
        setError("Too many attempts. Wait a minute and try again.");
        return;
      }
      if (!res.ok) {
        setError(flattenErrors(await res.json()));
        return;
      }

      // Registered. Log in right away so the user lands on the dashboard.
      const login = await apiFetch("/api/accounts/login/", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      if (login.ok) router.push("/dashboard");
      else router.push("/login");
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">Create account</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 w-72">
        <input
          className="border p-2"
          type="email"
          placeholder="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          className="border p-2"
          type="password"
          placeholder="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button type="submit" disabled={loading} className="bg-black text-white p-2 disabled:opacity-50">
          {loading ? "Creating..." : "Register"}
        </button>
      </form>
      {error && <p className="text-red-600 w-72 text-sm">{error}</p>}
      <p className="text-sm">
        Already have an account? <Link href="/login" className="underline">Log in</Link>
      </p>
    </main>
  );
}
