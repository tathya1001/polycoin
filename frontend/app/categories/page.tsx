"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import type { Category, Keyword } from "@/lib/types";

const URL = "/api/categories/";

export default function Categories() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [newTerms, setNewTerms] = useState<Record<string, string>>({}); // category id -> draft keyword

  // Bumping this re-runs the fetch effect below (after add / rename / delete).
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await apiFetch(URL);
        if (cancelled) return;
        if (res.ok) setCategories(await res.json());
        else setError(await readError(res, "Could not load categories."));
      } catch {
        if (!cancelled) setError("Cannot reach the server.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const res = await apiFetch(URL, {
      method: "POST",
      body: JSON.stringify({ name: newName.trim() }),
    });
    if (res.ok) {
      setNewName("");
      reload();
    } else {
      setError(await readError(res, "Could not add the category."));
    }
  }

  async function handleRename(category: Category) {
    setError(null);
    const res = await apiFetch(`${URL}${category.id}/`, {
      method: "PATCH",
      body: JSON.stringify({ name: editName.trim() }),
    });
    if (res.ok) {
      setEditingId(null);
      reload();
    } else {
      setError(await readError(res, "Could not rename the category."));
    }
  }

  async function handleDelete(category: Category) {
    if (!window.confirm(`Delete "${category.name}"?`)) return;
    setError(null);
    const res = await apiFetch(`${URL}${category.id}/`, { method: "DELETE" });
    if (res.ok) {
      reload();
    } else if (res.status === 409) {
      // The backend refuses (PROTECT) while transactions still use the category.
      setError("Move its transactions to another category first.");
    } else {
      setError(await readError(res, "Could not delete the category."));
    }
  }

  async function handleAddKeyword(e: React.FormEvent, category: Category) {
    e.preventDefault();
    const term = (newTerms[category.id] ?? "").trim();
    if (!term) return;
    setError(null);
    const res = await apiFetch(`${URL}${category.id}/keywords/`, {
      method: "POST",
      body: JSON.stringify({ term }),
    });
    if (res.ok) {
      setNewTerms((current) => ({ ...current, [category.id]: "" }));
      reload();
    } else {
      setError(await readError(res, "Could not add the keyword."));
    }
  }

  async function handleRemoveKeyword(category: Category, keyword: Keyword) {
    setError(null);
    const res = await apiFetch(`${URL}${category.id}/keywords/${keyword.id}/`, { method: "DELETE" });
    if (res.ok) reload();
    else setError(await readError(res, "Could not remove the keyword."));
  }

  function startEditing(category: Category) {
    setEditingId(category.id);
    setEditName(category.name);
    setError(null);
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Categories</h1>
        <Link href="/dashboard" className="text-sm underline">Dashboard</Link>
      </div>

      <p className="text-xs text-gray-500">
        Keywords help the AI recognise a category, e.g. &ldquo;swiggy&rdquo; or &ldquo;food delivery&rdquo;
        under Food. The category name is always used as well, so a new category works straight away.
      </p>

      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          className="flex-1 border p-2"
          placeholder="New category"
          maxLength={50}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          required
        />
        <button type="submit" className="bg-black text-white px-4 py-2">Add</button>
      </form>

      {error && <p className="text-red-600">{error}</p>}

      <ul className="flex flex-col divide-y border">
        {categories.map((category) => (
          <li key={category.id} className="flex flex-col gap-2 p-2">
            <div className="flex items-center gap-2">
              {editingId === category.id ? (
                <>
                  <input
                    className="flex-1 border p-1"
                    maxLength={50}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    autoFocus
                  />
                  <button onClick={() => handleRename(category)} className="text-sm underline">Save</button>
                  <button onClick={() => setEditingId(null)} className="text-sm underline">Cancel</button>
                </>
              ) : (
                <>
                  <span className="flex-1">{category.name}</span>
                  {category.is_default ? (
                    <span className="text-xs text-gray-500">default</span>
                  ) : (
                    <>
                      <button onClick={() => startEditing(category)} className="text-sm underline">Rename</button>
                      <button onClick={() => handleDelete(category)} className="text-sm text-red-600 underline">Delete</button>
                    </>
                  )}
                </>
              )}
            </div>

            {/* "Others" is where rows start and is never a target, so it has no keywords. */}
            {!category.is_default && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {category.keywords.map((keyword) => (
                  <span key={keyword.id} className="inline-flex items-center gap-1 rounded border px-2 py-0.5">
                    {keyword.term}
                    <button
                      aria-label={`Remove ${keyword.term}`}
                      onClick={() => handleRemoveKeyword(category, keyword)}
                      className="text-gray-500 hover:text-red-600"
                    >
                      &times;
                    </button>
                  </span>
                ))}
                <form onSubmit={(e) => handleAddKeyword(e, category)} className="inline-flex gap-1">
                  <input
                    className="w-40 border p-1"
                    placeholder="Add keyword"
                    aria-label={`Add a keyword to ${category.name}`}
                    maxLength={60}
                    value={newTerms[category.id] ?? ""}
                    onChange={(e) => setNewTerms((current) => ({ ...current, [category.id]: e.target.value }))}
                  />
                  <button type="submit" className="underline">Add</button>
                </form>
              </div>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}
