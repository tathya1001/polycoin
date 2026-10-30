"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { MAX_SOURCE_NAME, SOURCES_URL } from "@/lib/dataSources";
import { readError } from "@/lib/errors";
import { money } from "@/lib/format";
import type { DataSource } from "@/lib/types";
import { Button, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ColorPicker } from "@/components/ui/ColorPicker";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorNote, Loading } from "@/components/ui/Feedback";
import { Field, Input, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";

const COLOR_SAVE_DELAY_MS = 400; // dragging the colour wheel fires dozens of changes

type Usage = { transactions: number; links: number; panels: number };

export default function DataSources() {
  const toast = useToast();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [removing, setRemoving] = useState<DataSource | null>(null);
  const colorTimers = useRef(new Map<string, number>());

  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await apiFetch(SOURCES_URL);
        if (cancelled) return;
        if (res.ok) setSources(await res.json());
        else setError(await readError(res, "Could not load your data sources."));
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
    const res = await apiFetch(SOURCES_URL, { method: "POST", body: JSON.stringify({ name: newName }) });
    if (res.ok) {
      toast.success(`Added "${newName.trim()}".`);
      setNewName("");
      reload();
    } else {
      setError(await readError(res, "Could not add the data source."));
    }
  }

  async function handleRename(source: DataSource) {
    setError(null);
    const res = await apiFetch(`${SOURCES_URL}${source.id}/`, {
      method: "PATCH",
      body: JSON.stringify({ name: editName }),
    });
    if (res.ok) {
      setEditingId(null);
      reload();
    } else {
      setError(await readError(res, "Could not rename the data source."));
    }
  }

  // The swatch updates instantly; the server is told once the user pauses.
  function handleColor(source: DataSource, color: string) {
    setSources((all) => all.map((s) => (s.id === source.id ? { ...s, color } : s)));
    window.clearTimeout(colorTimers.current.get(source.id));
    colorTimers.current.set(
      source.id,
      window.setTimeout(async () => {
        colorTimers.current.delete(source.id);
        const res = await apiFetch(`${SOURCES_URL}${source.id}/`, {
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

  async function move(index: number, by: number) {
    const next = [...sources];
    const [source] = next.splice(index, 1);
    next.splice(index + by, 0, source);
    setSources(next);
    const res = await apiFetch(`${SOURCES_URL}reorder/`, {
      method: "POST",
      body: JSON.stringify({ order: next.map((s) => s.id) }),
    });
    if (!res.ok) {
      toast.error(await readError(res, "Could not change the order."));
      reload();
    }
  }

  if (loading) return <Loading />;

  return (
    <>
      <PageHeader
        title="Data Sources"
        subtitle="Keep each bank account's statements apart. Choose a source when you import, filter any chart by it, and name it in a formula. A source is only a label you pick, never bank details."
      />

      <form onSubmit={handleAdd} className="mb-5 flex gap-2">
        <Input
          className="flex-1"
          placeholder="New data source"
          aria-label="New data source name"
          maxLength={MAX_SOURCE_NAME}
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
          {sources.map((source, index) => (
            <li key={source.id} className="flex flex-col gap-2 p-4">
              <div className="flex items-center gap-3">
                <ColorPicker
                  value={source.color}
                  onChange={(color) => handleColor(source, color)}
                  label={`Colour for ${source.name}`}
                  size={26}
                />
                {editingId === source.id ? (
                  <>
                    <Input
                      dense
                      className="flex-1"
                      maxLength={MAX_SOURCE_NAME}
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRename(source);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      autoFocus
                    />
                    <IconButton label="Save name" size="sm" icon={<Check size={16} />} onClick={() => handleRename(source)} />
                    <IconButton label="Cancel" size="sm" icon={<X size={16} />} onClick={() => setEditingId(null)} />
                  </>
                ) : (
                  <>
                    <span className="flex-1 font-medium">{source.name}</span>
                    <IconButton
                      label={`Move ${source.name} up`}
                      size="sm"
                      icon={<ArrowUp size={15} />}
                      disabled={index === 0}
                      onClick={() => move(index, -1)}
                    />
                    <IconButton
                      label={`Move ${source.name} down`}
                      size="sm"
                      icon={<ArrowDown size={15} />}
                      disabled={index === sources.length - 1}
                      onClick={() => move(index, 1)}
                    />
                    <IconButton
                      label={`Rename ${source.name}`}
                      size="sm"
                      icon={<Pencil size={15} />}
                      onClick={() => {
                        setEditingId(source.id);
                        setEditName(source.name);
                        setError(null);
                      }}
                    />
                    <IconButton
                      label={`Delete ${source.name}`}
                      size="sm"
                      icon={<Trash2 size={15} />}
                      className="text-neg hover:bg-neg-bg"
                      disabled={sources.length === 1}
                      onClick={() => setRemoving(source)}
                    />
                  </>
                )}
              </div>
              <p className="pl-9.5 text-sm text-ink-2">
                {source.transactions.toLocaleString("en-IN")}{" "}
                {source.transactions === 1 ? "transaction" : "transactions"}
                {source.first_date && ` · ${source.first_date} to ${source.last_date}`}
                {source.balance !== null && ` · Balance ${money(source.balance)}`}
              </p>
            </li>
          ))}
        </ul>
      </Card>

      {removing && (
        <RemoveDialog
          source={removing}
          others={sources.filter((s) => s.id !== removing.id)}
          onClose={() => setRemoving(null)}
          onDone={() => {
            setRemoving(null);
            reload();
          }}
        />
      )}
    </>
  );
}

// Deleting asks what happens to the transactions, and says what else it touches.
function RemoveDialog({
  source,
  others,
  onClose,
  onDone,
}: {
  source: DataSource;
  others: DataSource[];
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [target, setTarget] = useState(others[0]?.id ?? "");
  const [keepRows, setKeepRows] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const res = await apiFetch(`${SOURCES_URL}${source.id}/usage/`);
      if (!cancelled && res.ok) setUsage(await res.json());
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [source.id]);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch(`${SOURCES_URL}${source.id}/remove/`, {
        method: "POST",
        body: JSON.stringify(keepRows ? { move_to: target } : {}),
      });
      if (res.ok) {
        toast.success(`Deleted "${source.name}".`);
        onDone();
      } else {
        setError(await readError(res, "Could not delete the data source."));
      }
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const hasRows = (usage?.transactions ?? 0) > 0;

  return (
    <Dialog
      open
      title={`Delete "${source.name}"?`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={busy} disabled={!usage} onClick={remove}>
            Delete
          </Button>
        </>
      }
    >
      {!usage ? (
        <Loading />
      ) : (
        <div className="space-y-3 text-sm">
          {hasRows && (
            <>
              <p>It holds {usage.transactions.toLocaleString("en-IN")} transactions.</p>
              <label className="flex items-center gap-2">
                <input type="radio" name="rows" checked={keepRows} onChange={() => setKeepRows(true)} />
                Move them to another data source
              </label>
              {keepRows && (
                <Field label="Move to">
                  <Select dense className="w-full" value={target} onChange={(e) => setTarget(e.target.value)}>
                    {others.map((other) => (
                      <option key={other.id} value={other.id}>
                        {other.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              <label className="flex items-center gap-2">
                <input type="radio" name="rows" checked={!keepRows} onChange={() => setKeepRows(false)} />
                Delete them too. This can&apos;t be undone.
              </label>
            </>
          )}
          {usage.links > 0 && (
            <p>
              {usage.links} linked {usage.links === 1 ? "transfer" : "transfers"} may lose the link, and the other
              side will count as normal spending or income again.
            </p>
          )}
          {usage.panels > 0 && (
            <p>
              {usage.panels} {usage.panels === 1 ? "panel uses" : "panels use"} this source. They will show an error
              until you choose another one.
            </p>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
        </div>
      )}
    </Dialog>
  );
}
