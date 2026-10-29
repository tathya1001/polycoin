"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { CheckCircle2, Eye, EyeOff, FileSpreadsheet, FileText, Info, KeyRound, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { readError } from "@/lib/errors";
import { money } from "@/lib/format";
import { convertPdf, isPdf, PdfProblem } from "@/lib/pdfText";
import type { ImportResult, ImportRowError, Mapping, MappingField, Preview } from "@/lib/types";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorNote, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Stepper } from "@/components/ui/Stepper";
import { MoneyCell, Table, Td, Th, Tr } from "@/components/ui/Table";
import { useToast } from "@/components/ui/Toast";

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

const ACCEPTED = ".xlsx,.xls,.csv,.pdf";

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

export default function ImportStatement() {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  // What the server receives: the chosen file, or for a PDF the CSV table read from it here.
  const [upload, setUpload] = useState<File | null>(null);
  // For a PDF, the page each uploaded row came from (row N is pdfPages[N - 1]).
  const [pdfPages, setPdfPages] = useState<number[] | null>(null);
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

  const fromPdf = file !== null && isPdf(file);
  // A PDF is unlocked here in the browser; its CSV table needs no password on the server.
  const serverPassword = fromPdf ? "" : password;

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

  // Reads the PDF's table in the browser once; every later call uploads the resulting CSV.
  async function readPdf(f: File, pw: string) {
    const requestId = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const { csv, pages } = await convertPdf(f, pw);
      if (requestId !== latestRequest.current) return;
      setUpload(csv);
      setPdfPages(pages);
      setNeedsPassword(false);
      await runPreview(csv, "", null);
    } catch (err) {
      if (requestId !== latestRequest.current) return;
      if (!(err instanceof PdfProblem)) {
        setError("This PDF couldn't be read.");
      } else if (err.code === "password_required" || err.code === "wrong_password") {
        setNeedsPassword(true);
        if (err.code === "wrong_password") setError(err.message);
      } else {
        setError(err.message);
      }
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0] ?? null;
    setFile(chosen);
    setUpload(null);
    setPdfPages(null);
    setPassword("");
    setNeedsPassword(false);
    setHeaders([]);
    setMapping(null);
    setPreview(null);
    setResult(null);
    setError(null);
    if (!chosen) return;
    if (isPdf(chosen)) {
      readPdf(chosen, "");
    } else {
      setUpload(chosen);
      runPreview(chosen, "", null);
    }
  }

  function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    if (fromPdf) readPdf(file, password);
    else runPreview(file, password, mapping);
  }

  function handleMappingChange(field: MappingField, value: string) {
    if (!upload) return;
    const next: Mapping = { ...mapping };
    if (value === "") delete next[field];
    else next[field] = Number(value);
    setMapping(next);
    runPreview(upload, serverPassword, next);
  }

  async function handleConfirm() {
    if (!upload || !mapping) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(IMPORT_URL, {
        method: "POST",
        body: buildForm(upload, serverPassword, mapping),
      });
      if (res.ok) {
        const done: ImportResult = await res.json();
        setResult(done);
        setPreview(null);
        toast.success(`${done.imported} transactions imported.`);
      } else {
        setError(await readError(res, "Import failed."));
      }
    } catch {
      setError("Cannot reach the server.");
    } finally {
      setLoading(false);
    }
  }

  const step = result ? 2 : preview || (needsPassword && file) ? 1 : 0;

  return (
    <>
      <PageHeader
        title="Import statement"
        subtitle="The file is read and discarded. Only the transactions are saved, encrypted."
      />
      <Stepper steps={["Upload", "Check & preview", "Done"]} current={step} />

      {/* 1. pick a file */}
      {!result && (
        <label
          htmlFor="statement"
          className="mb-5 flex cursor-pointer items-center gap-4 rounded-md border-[1.5px] border-dashed border-ink bg-surface p-5 transition-colors hover:bg-wash has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ink"
        >
          <span className="grid size-12 shrink-0 place-items-center rounded-full border-[1.5px] border-ink bg-canvas">
            {!file ? (
              <Upload size={22} aria-hidden />
            ) : fromPdf ? (
              <FileText size={22} aria-hidden />
            ) : (
              <FileSpreadsheet size={22} aria-hidden />
            )}
          </span>
          <span className="flex-1">
            <span className="block font-semibold">{file ? file.name : "Choose a bank statement"}</span>
            <span className="block text-sm text-ink-2">
              {file ? "Click to choose a different file." : "Excel, CSV or PDF, up to 5 MB"}
            </span>
          </span>
          {loading && <Spinner />}
          <input id="statement" type="file" accept={ACCEPTED} onChange={handleFileChange} className="sr-only" />
        </label>
      )}

      {/* 2. password, only if the server says the file is protected */}
      {needsPassword && (
        <Card className="mb-5">
          <form onSubmit={handlePasswordSubmit} className="space-y-3">
            <p className="flex items-center gap-2 font-medium">
              <KeyRound size={18} aria-hidden /> This file is password-protected.
            </p>
            <div className="flex gap-2">
              <Input
                className="flex-1"
                type={showPassword ? "text" : "password"}
                placeholder="File password"
                aria-label="File password"
                // "off" is ignored for password fields; "new-password" stops the browser
                // pre-filling the saved polycoin LOGIN password into this box.
                autoComplete="new-password"
                name="statement-file-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <Button
                variant="ghost"
                aria-label={showPassword ? "Hide password" : "Show password"}
                icon={showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                onClick={() => setShowPassword((s) => !s)}
              />
              <Button type="submit" variant="primary" loading={loading}>
                Unlock
              </Button>
            </div>
          </form>
        </Card>
      )}

      {error && <ErrorNote className="mb-5">{error}</ErrorNote>}

      {/* 3. check the column mapping */}
      {headers.length > 0 && mapping && !result && (
        <section className="mb-6">
          <h2 className="text-lg font-semibold tracking-tight">Check the columns</h2>
          <p className="mb-3 text-sm text-ink-2">
            We detected these. Fix any that are wrong. Use Debit + Credit, or a single Amount column.
          </p>
          <Card className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {FIELDS.map(({ key, label }) => (
              <Field key={key} label={label}>
                <Select
                  dense
                  className="w-full"
                  value={mapping[key] ?? ""}
                  onChange={(e) => handleMappingChange(key, e.target.value)}
                >
                  <option value="">(none)</option>
                  {headers.map((header, index) => (
                    <option key={index} value={index}>
                      {index + 1}: {header || "(blank)"}
                    </option>
                  ))}
                </Select>
              </Field>
            ))}
          </Card>
        </section>
      )}

      {/* preview */}
      {preview && !result && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold tracking-tight">
            Preview: {preview.row_count} transactions
            {preview.error_count > 0 && `, ${preview.error_count} rows with problems`}
          </h2>
          {fromPdf && (
            <p className="flex items-center gap-2 text-sm text-ink-2">
              <Info size={16} aria-hidden /> This table was rebuilt from a PDF. Check the rows below
              before you import.
            </p>
          )}
          <Table>
            <thead>
              <Tr className="hover:bg-transparent">
                <Th>Date</Th>
                <Th>Name</Th>
                <Th align="right">Amount</Th>
                <Th align="right">Balance</Th>
                <Th>Description</Th>
              </Tr>
            </thead>
            <tbody>
              {preview.sample.map((row) => (
                <Tr key={row.row}>
                  <Td className="whitespace-nowrap text-ink-2">{row.date}</Td>
                  <Td className="font-medium">{row.name}</Td>
                  <MoneyCell value={row.amount} type={row.txn_type} />
                  <Td align="right" className="whitespace-nowrap text-ink-2">
                    {row.balance === null ? "" : money(row.balance)}
                  </Td>
                  <Td className="max-w-xs truncate text-ink-2" title={row.description}>
                    {row.description}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
          {preview.row_count > preview.sample.length && (
            <p className="text-xs text-muted">Showing the first {preview.sample.length}.</p>
          )}
          {preview.errors.length > 0 && (
            <RowErrors errors={preview.errors} total={preview.error_count} pages={pdfPages} />
          )}

          {/* 4. confirm */}
          <Button variant="primary" loading={loading} disabled={preview.row_count === 0} onClick={handleConfirm}>
            Import {preview.row_count} transactions
          </Button>
        </section>
      )}

      {result && (
        <Card className="space-y-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <CheckCircle2 size={20} className="text-pos" aria-hidden /> Import finished
          </h2>
          <p>
            {result.imported} imported, {result.duplicates} skipped as duplicates.
          </p>
          {result.errors.length > 0 && (
            <RowErrors errors={result.errors} total={result.errors.length} pages={pdfPages} />
          )}
          <div className="flex flex-wrap gap-2">
            <Link href="/transactions" className={buttonClass("primary", "md")}>
              View transactions
            </Link>
            <Link href="/transactions/categorize" className={buttonClass("secondary", "md")}>
              Categorize with AI
            </Link>
            <Link href="/ask" className={buttonClass("ghost", "md")}>
              Update the Ask index
            </Link>
          </div>
        </Card>
      )}
    </>
  );
}

// A row number inside a table rebuilt from a PDF means nothing to the user; its page does.
function RowErrors({
  errors,
  total,
  pages,
}: {
  errors: ImportRowError[];
  total: number;
  pages: number[] | null;
}) {
  const where = (row: number) => {
    const page = pages?.[row - 1];
    return page ? `Page ${page}` : `Row ${row}`;
  };
  return (
    <div className="rounded-sm border-[1.5px] border-neg bg-[#fff1f1] p-3 text-sm text-neg">
      <p className="font-medium">
        Rows we couldn&apos;t read{total > errors.length ? ` (showing ${errors.length} of ${total})` : ""}:
      </p>
      <ul className="mt-1 list-disc pl-5">
        {errors.map((e) => (
          <li key={e.row}>
            {where(e.row)}: {e.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
