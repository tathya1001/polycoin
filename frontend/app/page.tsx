"use client";

import { useEffect, useState } from "react";

type Status = "loading" | "ok" | "error";

export default function Home() {
  const [status, setStatus] = useState<Status>("loading");
  const [database, setDatabase] = useState<string | null>(null);

  useEffect(() => {
    async function checkHealth() {
      try {
        const res = await fetch("/api/health/");
        const data = await res.json();
        setStatus(res.ok ? "ok" : "error");
        setDatabase(data.database ?? null);
      } catch {
        setStatus("error");
      }
    }

    checkHealth();
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center">
      {status === "loading" && <p className="text-gray-500">Checking...</p>}
      {status === "ok" && (
        <p className="text-green-600 text-xl">
          Connected (database: {database})
        </p>
      )}
      {status === "error" && (
        <p className="text-red-600 text-xl">Cannot reach backend</p>
      )}
    </main>
  );
}
