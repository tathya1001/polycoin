"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import type { ImportResult, Mapping, MappingField, Preview } from "@/lib/types";

const PREVIEW_URL = "/api/transactions/import/preview/";
const IMPORT_URL = "/api/transactions/import/";

const FIELDS: { key: MappingField; label: string }[] = [
  { key: "date", label: "Date" },
  { key: "description", label: "Description / narration" },
  { key: "debit", label: "Debit (withdrawal)" },
  { key: "credit", label: "Credit (deposit)" },
  { key: "amount", label: "Amount (if one column)" },
  { key: "type", label: "Dr/Cr (if one amount column)" },
  { key: "balance", label: "Balance" },
];

// The server stores nothing, so every call re-sends the file (and password, and mapping).
function buildForm(file: File, password: string, mapping: Mapping | null) {
  const form = new FormData();
  form.append("file", file);
  if (password) form.append("password", password);
  if (mapping) form.append("mapping", JSON.stringify(mapping));
  return form;
}

async function readCode(res: Response): Promise<string | undefined> {
  try {
    return (await res.clone().json())?.code;
  } catch {
    return undefined;
  }
}

function money(value: string | null) {
  if (value === null) return "";
  return Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

export default function ImportStatement() {
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only the newest preview request may update the screen (dropdowns can fire quickly).
  const latestRequest = useRef(0);

  async function runPreview(f: File, pw: string, m: Mapping | null) {
    const requestId = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(PREVIEW_URL, {
        method: "POST",
        body: buildForm(f, pw, m),
      });
      if (requestId !== latestRequest.current) return;

      if (res.ok) {
        const data: Preview = await res.json();
        setPreview(data);
        setHeaders(data.headers);
        setNeedsPassword(false);
        setMapping((current) => current ?? data.detected_mapping);
        return;
      }

      setPreview(null);
      const code = await readCode(res);
      if (code === "password_required") {
        setNeedsPassword(true);
      } else if (code === "wrong_password") {
        setNeedsPassword(true);
        setError("That password is incorrect.");
      } else {
        setError(await readError(res, "Could not read that file."));
      }
    } catch {
      if (requestId === latestRequest.current) setError("Cannot reach the server.");
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0] ?? null;
    setFile(chosen);
    setPassword("");
    setNeedsPassword(false);
    setHeaders([]);
    setMapping(null);
    setPreview(null);
    setResult(null);
    setError(null);
    if (chosen) runPreview(chosen, "", null);
  }

  function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (file) runPreview(file, password, mapping);
  }

  function handleMappingChange(field: MappingField, value: string) {
    if (!file) return;
    const next: Mapping = { ...mapping };
    if (value === "") delete next[field];
    else next[field] = Number(value);
    setMapping(next);
    runPreview(file, password, next);
  }

  async function handleConfirm() {
    if (!file || !mapping) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(IMPORT_URL, {
        method: "POST",
        body: buildForm(file, password, mapping),
      });
      if (res.ok) {
        setResult(await res.json());
        setPreview(null);
      } else {
        setError(await readError(res, "Import failed."));
      }
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Import statement</h1>
        <Link href="/transactions" className="text-sm underline">Transactions</Link>
      </div>

      {/* 1. pick a file */}
      <div className="flex flex-col gap-1">
        <label className="text-sm" htmlFor="statement">Bank statement (.xlsx, max 5 MB)</label>
        <input
          id="statement"
          type="file"
          accept=".xlsx"
          onChange={handleFileChange}
          className="border p-2"
        />
        <p className="text-xs text-gray-500">
          The file is read and discarded. Only the transactions are saved, encrypted.
        </p>
      </div>

      {/* 2. password, only if the server says the file is protected */}
      {needsPassword && (
        <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-2 border p-3">
          <p className="text-sm">This file is password-protected. Enter its password.</p>
          <div className="flex gap-2">
            <input
              className="flex-1 border p-2"
              type={showPassword ? "text" : "password"}
              placeholder="file password"
              // "off" is ignored for password fields; "new-password" stops the browser
              // pre-filling the saved polycoin LOGIN password into this box.
              autoComplete="new-password"
              name="statement-file-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="text-sm underline"
            >
              {showPassword ? "Hide" : "Show"}
            </button>
            <button type="submit" disabled={loading} className="bg-black text-white px-4 py-2 disabled:opacity-50">
              Unlock
            </button>
          </div>
        </form>
      )}

      {loading && <p className="text-gray-500">Working...</p>}
      {error && <p className="text-red-600">{error}</p>}

      {/* 3. check the column mapping */}
      {headers.length > 0 && mapping && !result && (
        <section className="flex flex-col gap-2">
          <h2 className="font-semibold">Check the columns</h2>
          <p className="text-sm text-gray-500">
            We detected these. Fix any that are wrong. Use Debit + Credit, or a single Amount column.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {FIELDS.map(({ key, label }) => (
              <label key={key} className="flex items-center justify-between gap-2 text-sm">
                {label}
                <select
                  className="w-48 border p-1"
                  value={mapping[key] ?? ""}
                  onChange={(e) => handleMappingChange(key, e.target.value)}
                >
                  <option value="">(none)</option>
                  {headers.map((header, index) => (
                    <option key={index} value={index}>
                      {index + 1}: {header || "(blank)"}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </section>
      )}

      {/* preview */}
      {preview && !result && (
        <section className="flex flex-col gap-2">
          <h2 className="font-semibold">
            Preview: {preview.row_count} transactions
            {preview.error_count > 0 && `, ${preview.error_count} rows with problems`}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-1">Date</th>
                  <th className="p-1">Name</th>
                  <th className="p-1 text-right">Amount</th>
                  <th className="p-1 text-right">Balance</th>
                  <th className="p-1">Description</th>
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((row) => (
                  <tr key={row.row} className="border-b">
                    <td className="p-1 whitespace-nowrap">{row.date}</td>
                    <td className="p-1">{row.name}</td>
                    <td className={`p-1 text-right whitespace-nowrap ${row.txn_type === "credit" ? "text-green-600" : "text-red-600"}`}>
                      {row.txn_type === "credit" ? "+" : "-"}{money(row.amount)}
                    </td>
                    <td className="p-1 text-right whitespace-nowrap">{money(row.balance)}</td>
                    <td className="max-w-xs truncate p-1" title={row.description}>{row.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.row_count > preview.sample.length && (
            <p className="text-xs text-gray-500">Showing the first {preview.sample.length}.</p>
          )}
          {preview.errors.length > 0 && <RowErrors errors={preview.errors} total={preview.error_count} />}

          {/* 4. confirm */}
          <button
            onClick={handleConfirm}
            disabled={loading || preview.row_count === 0}
            className="self-start bg-black text-white px-4 py-2 disabled:opacity-50"
          >
            Import {preview.row_count} transactions
          </button>
        </section>
      )}

      {result && (
        <section className="flex flex-col gap-2 border p-3">
          <h2 className="font-semibold">Import finished</h2>
          <p>{result.imported} imported, {result.duplicates} skipped as duplicates.</p>
          {result.errors.length > 0 && <RowErrors errors={result.errors} total={result.errors.length} />}
          <Link href="/transactions" className="underline">View transactions</Link>
        </section>
      )}
    </main>
  );
}

function RowErrors({ errors, total }: { errors: { row: number; reason: string }[]; total: number }) {
  return (
    <div className="text-sm text-red-600">
      <p>Rows we couldn&apos;t read{total > errors.length ? ` (showing ${errors.length} of ${total})` : ""}:</p>
      <ul className="list-disc pl-5">
        {errors.map((e) => (
          <li key={e.row}>Row {e.row}: {e.reason}</li>
        ))}
      </ul>
    </div>
  );
}
