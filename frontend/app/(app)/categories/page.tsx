"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import type { Category, Keyword } from "@/lib/types";
import { Button, IconButton } from "@/components/ui/Button";
import { Badge, Card, Chip } from "@/components/ui/Card";
import { useConfirm } from "@/components/ui/Confirm";
import { ColorPicker } from "@/components/ui/ColorPicker";
import { ErrorNote, Loading } from "@/components/ui/Feedback";
import { Input } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";

const URL = "/api/categories/";
const COLOR_SAVE_DELAY_MS = 400; // dragging the colour wheel fires dozens of changes

export default function Categories() {
  const toast = useToast();
  const confirm = useConfirm();
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [newTerms, setNewTerms] = useState<Record<string, string>>({}); // category id -> draft keyword
  const colorTimers = useRef(new Map<string, number>());

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

  // Pending colour saves must not fire after the page is gone.
  useEffect(() => {
    const timers = colorTimers.current;
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const res = await apiFetch(URL, {
      method: "POST",
      body: JSON.stringify({ name: newName.trim() }),
    });
    if (res.ok) {
      toast.success(`Added "${newName.trim()}".`);
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
    const ok = await confirm({
      title: `Delete "${category.name}"?`,
      message: "Its keywords are deleted too. This only works once no transaction uses it.",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    setError(null);
    const res = await apiFetch(`${URL}${category.id}/`, { method: "DELETE" });
    if (res.ok) {
      toast.success(`Deleted "${category.name}".`);
      reload();
    } else if (res.status === 409) {
      // The backend refuses (PROTECT) while transactions still use the category.
      toast.error("Move its transactions to another category first.");
    } else {
      toast.error(await readError(res, "Could not delete the category."));
    }
  }

  // The swatch updates instantly; the server is told once the user pauses.
  function handleColor(category: Category, color: string) {
    setCategories((all) => all.map((c) => (c.id === category.id ? { ...c, color } : c)));
    window.clearTimeout(colorTimers.current.get(category.id));
    colorTimers.current.set(
      category.id,
      window.setTimeout(async () => {
        colorTimers.current.delete(category.id);
        const res = await apiFetch(`${URL}${category.id}/`, {
          method: "PATCH",
          body: JSON.stringify({ color }),
        });
        if (!res.ok) {
          toast.error(await readError(res, "Could not save the colour."));
          reload();
        }
      }, COLOR_SAVE_DELAY_MS),
    );
  }

  async function handleAddKeyword(e: React.FormEvent, category: Category) {
    e.preventDefault();
    const term = (newTerms[category.id] ?? "").trim();
    if (!term) return;
    const res = await apiFetch(`${URL}${category.id}/keywords/`, {
      method: "POST",
      body: JSON.stringify({ term }),
    });
    if (res.ok) {
      setNewTerms((current) => ({ ...current, [category.id]: "" }));
      reload();
    } else {
      toast.error(await readError(res, "Could not add the keyword."));
    }
  }

  async function handleRemoveKeyword(category: Category, keyword: Keyword) {
    const res = await apiFetch(`${URL}${category.id}/keywords/${keyword.id}/`, { method: "DELETE" });
    if (res.ok) reload();
    else toast.error(await readError(res, "Could not remove the keyword."));
  }

  function startEditing(category: Category) {
    setEditingId(category.id);
    setEditName(category.name);
    setError(null);
  }

  if (loading) return <Loading />;

  return (
    <>
      <PageHeader
        title="Categories"
        subtitle={
          <>
            Each category has a colour: it is the default in every chart. Keywords help the AI recognise a
            category, e.g. &ldquo;takeaway&rdquo; under Food. The name is always used as well.
          </>
        }
      />

      <form onSubmit={handleAdd} className="mb-5 flex gap-2">
        <Input
          className="flex-1"
          placeholder="New category"
          aria-label="New category name"
          maxLength={50}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          required
        />
        <Button type="submit" variant="primary" icon={<Plus size={16} />}>
          Add
        </Button>
      </form>

      {error && <ErrorNote className="mb-4">{error}</ErrorNote>}

      <Card padded={false}>
        <ul className="divide-y divide-hairline">
          {categories.map((category) => (
            <li key={category.id} className="flex flex-col gap-3 p-4">
              <div className="flex items-center gap-3">
                <ColorPicker
                  value={category.color}
                  onChange={(color) => handleColor(category, color)}
                  label={`Colour for ${category.name}`}
                  size={26}
                />
                {editingId === category.id ? (
                  <>
                    <Input
                      dense
                      className="flex-1"
                      maxLength={50}
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRename(category);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      autoFocus
                    />
                    <IconButton label="Save name" size="sm" icon={<Check size={16} />} onClick={() => handleRename(category)} />
                    <IconButton label="Cancel" size="sm" icon={<X size={16} />} onClick={() => setEditingId(null)} />
                  </>
                ) : (
                  <>
                    <span className="flex-1 font-medium">{category.name}</span>
                    {category.is_default ? (
                      <Badge>default</Badge>
                    ) : (
                      <>
                        <IconButton
                          label={`Rename ${category.name}`}
                          size="sm"
                          icon={<Pencil size={15} />}
                          onClick={() => startEditing(category)}
                        />
                        <IconButton
                          label={`Delete ${category.name}`}
                          size="sm"
                          icon={<Trash2 size={15} />}
                          className="text-neg hover:bg-[#fee2e2]"
                          onClick={() => handleDelete(category)}
                        />
                      </>
                    )}
                  </>
                )}
              </div>

              {/* "Others" is where rows start and is never a target, so it has no keywords. */}
              {!category.is_default && (
                <div className="flex flex-wrap items-center gap-2 pl-9.5">
                  {category.keywords.map((keyword) => (
                    <Chip key={keyword.id} onRemove={() => handleRemoveKeyword(category, keyword)}>
                      {keyword.term}
                    </Chip>
                  ))}
                  <form onSubmit={(e) => handleAddKeyword(e, category)} className="inline-flex gap-1.5">
                    <Input
                      dense
                      className="w-40"
                      placeholder="Add keyword"
                      aria-label={`Add a keyword to ${category.name}`}
                      maxLength={60}
                      value={newTerms[category.id] ?? ""}
                      onChange={(e) => setNewTerms((current) => ({ ...current, [category.id]: e.target.value }))}
                    />
                    <Button type="submit" size="sm">
                      Add
                    </Button>
                  </form>
                </div>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
