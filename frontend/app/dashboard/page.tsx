"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Me = { id: string; email: string; date_joined: string };

export default function Dashboard() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadMe() {
      // apiFetch refreshes an expired access token and retries; if the session is
      // really gone it redirects to /login itself.
      const res = await apiFetch("/api/accounts/me/");
      if (res.ok) setMe(await res.json());
      setLoading(false);
    }
    loadMe();
  }, []);

  async function handleLogout() {
    await apiFetch("/api/accounts/logout/", { method: "POST" });
    router.push("/login");
  }

  if (loading) {
    return <main className="flex min-h-screen items-center justify-center"><p className="text-gray-500">Loading...</p></main>;
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      {me && <p>Logged in as <strong>{me.email}</strong></p>}
      <nav className="flex gap-4 underline">
        <Link href="/transactions">Transactions</Link>
        <Link href="/transactions/import">Import statement</Link>
        <Link href="/categories">Categories</Link>
      </nav>
      <button onClick={handleLogout} className="bg-black text-white px-4 py-2">
        Log out
      </button>
    </main>
  );
}
