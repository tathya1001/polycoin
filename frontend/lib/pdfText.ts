// Reads a PDF statement in the browser and turns it into a CSV file the import endpoint accepts.
// The PDF itself never leaves the device. pdf.js is loaded only when a PDF is picked.

import { buildTable, NoTableHeader, toCsv, type TextPiece } from "@/lib/pdfTable";

export const MAX_PDF_PAGES = 100;

export type PdfProblemCode =
  | "unsupported_browser"
  | "password_required"
  | "wrong_password"
  | "too_many_pages"
  | "scanned"
  | "no_table"
  | "unreadable";

export class PdfProblem extends Error {
  constructor(
    readonly code: PdfProblemCode,
    message: string,
  ) {
    super(message);
    this.name = "PdfProblem";
  }
}

export type ConvertedPdf = {
  csv: File;
  /** The 1-based PDF page of each CSV row (index 0 is the header row). */
  pages: number[];
};

export function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

async function loadPdfJs() {
  let pdfjs;
  try {
    pdfjs = await import("pdfjs-dist");
  } catch {
    // pdf.js targets current browsers (it uses recent JavaScript built-ins at load time).
    throw new PdfProblem(
      "unsupported_browser",
      "This browser can't read PDFs here. Update it, or upload a CSV or Excel statement.",
    );
  }
  if (!pdfjs.GlobalWorkerOptions.workerSrc) {
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();
  }
  return pdfjs;
}

export async function convertPdf(file: File, password: string): Promise<ConvertedPdf> {
  const pdfjs = await loadPdfJs();
  let task: ReturnType<typeof pdfjs.getDocument> | undefined;

  try {
    task = pdfjs.getDocument({
      data: new Uint8Array(await file.arrayBuffer()),
      password: password || undefined,
      // Only text is read, never rendered: warnings about fonts the PDF doesn't embed are noise.
      verbosity: pdfjs.VerbosityLevel.ERRORS,
    });
    const doc = await task.promise;
    if (doc.numPages > MAX_PDF_PAGES) {
      throw new PdfProblem(
        "too_many_pages",
        `This PDF has ${doc.numPages} pages (limit ${MAX_PDF_PAGES}). Split the statement.`,
      );
    }

    const pages: TextPiece[][] = [];
    for (let number = 1; number <= doc.numPages; number++) {
      const page = await doc.getPage(number);
      const viewport = page.getViewport({ scale: 1 });
      const content = await page.getTextContent();
      const pieces: TextPiece[] = [];
      for (const item of content.items) {
        if (!("str" in item) || item.str.trim() === "") continue;
        // The text matrix's last two entries are the baseline origin in PDF space (y up);
        // the viewport turns that into top-left page coordinates, honouring page rotation.
        const [x, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
        const height = item.height || Math.hypot(item.transform[2], item.transform[3]);
        pieces.push({ text: item.str, x0: x, x1: x + item.width, y, height });
      }
      pages.push(pieces);
      page.cleanup();
    }

    if (pages.every((pieces) => pieces.length === 0)) {
      throw new PdfProblem(
        "scanned",
        "This PDF is a scanned image, so its text can't be read. Download a CSV or Excel statement instead.",
      );
    }

    const table = buildTable(pages);
    const name = file.name.replace(/\.pdf$/i, "") + ".csv";
    return { csv: new File([toCsv(table.rows)], name, { type: "text/csv" }), pages: table.pages };
  } catch (error) {
    if (error instanceof PdfProblem) throw error;
    if (error instanceof NoTableHeader) throw new PdfProblem("no_table", error.message);
    if (error instanceof pdfjs.PasswordException) {
      throw error.code === pdfjs.PasswordResponses.INCORRECT_PASSWORD
        ? new PdfProblem("wrong_password", "That password is incorrect.")
        : new PdfProblem("password_required", "This file is password-protected.");
    }
    // A damaged or hostile file can fail anywhere inside pdf.js: it is simply unreadable.
    throw new PdfProblem("unreadable", "This PDF couldn't be read.");
  } finally {
    await task?.destroy();
  }
}
