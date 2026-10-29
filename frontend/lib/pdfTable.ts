// Rebuilds a bank statement's transaction table from the positioned text of a PDF.
//
// A PDF has no table, only text drawn at coordinates. Statements line their columns up under a
// header row, so the header's positions are the column guide: every piece of text goes to the
// column it overlaps most. Pure logic: lib/pdfText.ts gets the text out of the PDF with pdf.js.

/** One run of text. Coordinates are page units from the top-left; `y` is the baseline. */
export type TextPiece = { text: string; x0: number; x1: number; y: number; height: number };

/** `pages[i]` is the 1-based page that `rows[i]` came from; rows[0] is the header. */
export type PdfTable = { rows: string[][]; pages: number[] };

export class NoTableHeader extends Error {
  constructor() {
    super("Couldn't find the header row of the transaction table in this PDF.");
    this.name = "NoTableHeader";
  }
}

// The server's header synonyms (backend/transactions/importer.py _SYNONYMS); keep the two in step.
// Here they only locate the columns: the server still detects the header in the uploaded table.
const SYNONYMS: Record<string, string[]> = {
  date: ["date", "txn date", "tran date", "transaction date", "posting date"],
  description: [
    "narration", "description", "particulars", "remarks", "details",
    "transaction remarks", "transaction details",
  ],
  debit: [
    "debit", "dr", "debit amount", "debit amt", "withdrawal", "withdrawals",
    "withdrawal amt", "withdrawal amount",
  ],
  credit: [
    "credit", "cr", "credit amount", "credit amt", "deposit", "deposits",
    "deposit amt", "deposit amount",
  ],
  amount: ["amount", "txn amount", "transaction amount"],
  type: ["dr cr", "cr dr", "type", "transaction type"],
  balance: ["balance", "closing balance", "running balance", "available balance"],
};
const FIELD_BY_HEADER = new Map(
  Object.entries(SYNONYMS).flatMap(([field, texts]) => texts.map((text) => [text, field] as const)),
);

const MIN_HEADER_FIELDS = 2; // one stray "Date" isn't a header (as on the server)
const SAME_LINE = 0.5; // baselines closer than this share a line, × text height
const SAME_PHRASE = 0.6; // a gap narrower than this keeps words in one header cell, × height
const NO_SPACE = 0.15; // a gap narrower than this is inside a word, × height
const WRAP_GAP = 1.5; // a continuation line sits at most this far below, × the usual line pitch

type Line = { y: number; pieces: TextPiece[] };
type Header = { line: Line; columns: number[]; fields: Map<string, number> };

/** "Withdrawal Amt." -> "withdrawal amt", as the server's _norm does. */
export function normalise(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

/** The low median: with an even count it takes the smaller middle value, so one large outlier
 *  (the gap down to a footer) can't become the "usual" line pitch of a short page. */
function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

function groupLines(pieces: TextPiece[]): Line[] {
  const visible = pieces.filter((p) => p.text.trim() !== "");
  const tolerance = SAME_LINE * (median(visible.map((p) => p.height)) || 6);
  const lines: Line[] = [];
  for (const piece of [...visible].sort((a, b) => a.y - b.y || a.x0 - b.x0)) {
    const last = lines.at(-1);
    if (last && Math.abs(piece.y - last.y) <= tolerance) last.pieces.push(piece);
    else lines.push({ y: piece.y, pieces: [piece] });
  }
  for (const line of lines) line.pieces.sort((a, b) => a.x0 - b.x0);
  return lines;
}

/** Pieces left to right as one string, with spaces only where there is a visible gap. */
function joinPieces(pieces: TextPiece[]): string {
  let text = "";
  let previous: TextPiece | null = null;
  for (const piece of pieces) {
    const word = piece.text.trim();
    if (previous && piece.x0 - previous.x1 > NO_SPACE * piece.height) text += " ";
    text += word;
    previous = piece;
  }
  return text;
}

/** Neighbouring pieces with a small gap form one cell: "Withdrawal" + "Amt." is one header. */
function phrases(line: Line): TextPiece[] {
  const merged: TextPiece[] = [];
  let group: TextPiece[] = [];
  const flush = () => {
    if (group.length === 0) return;
    merged.push({
      text: joinPieces(group),
      x0: group[0].x0,
      x1: Math.max(...group.map((p) => p.x1)),
      y: group[0].y,
      height: Math.max(...group.map((p) => p.height)),
    });
    group = [];
  };
  for (const piece of line.pieces) {
    const last = group.at(-1);
    if (last && piece.x0 - last.x1 > SAME_PHRASE * piece.height) flush();
    group.push(piece);
  }
  flush();
  return merged;
}

/** The line that names the most known fields, if it names enough of them. */
function findHeader(lines: Line[]): Header | null {
  let best: Header | null = null;
  for (const line of lines) {
    const cells = phrases(line);
    const fields = new Map<string, number>();
    cells.forEach((cell, column) => {
      const field = FIELD_BY_HEADER.get(normalise(cell.text));
      if (field && !fields.has(field)) fields.set(field, column);
    });
    if (fields.size >= MIN_HEADER_FIELDS && fields.size > (best?.fields.size ?? 0)) {
      // Column i owns the x range between the midpoints to its neighbours' header cells.
      const bounds = cells.slice(1).map((cell, i) => (cells[i].x1 + cell.x0) / 2);
      best = { line: { ...line, pieces: cells }, columns: bounds, fields };
    }
  }
  return best;
}

function sameFields(a: Header, b: Header): boolean {
  return a.fields.size === b.fields.size && [...a.fields.keys()].every((field) => b.fields.has(field));
}

function columnOf(piece: TextPiece, bounds: number[]): number {
  let bestColumn = 0;
  let bestOverlap = -Infinity;
  for (let column = 0; column <= bounds.length; column++) {
    const left = column === 0 ? -Infinity : bounds[column - 1];
    const right = column === bounds.length ? Infinity : bounds[column];
    const overlap = Math.min(piece.x1, right) - Math.max(piece.x0, left);
    if (overlap > bestOverlap) [bestColumn, bestOverlap] = [column, overlap];
  }
  return bestColumn;
}

function cellsOf(line: Line, bounds: number[]): string[] {
  const buckets: TextPiece[][] = Array.from({ length: bounds.length + 1 }, () => []);
  for (const piece of line.pieces) buckets[columnOf(piece, bounds)].push(piece);
  return buckets.map(joinPieces);
}

/**
 * The statement's table, from every page's text. Lines above a page's header (logos, address
 * blocks) are dropped, a header repeated on a later page re-reads the columns and is dropped,
 * and a page without a header uses the previous page's columns. A narration that wraps onto
 * the next line is joined back into its transaction.
 */
export function buildTable(pages: TextPiece[][]): PdfTable {
  const rows: string[][] = [];
  const rowPages: number[] = [];
  let header: Header | null = null;

  for (const [index, pieces] of pages.entries()) {
    const pageNumber = index + 1;
    const lines = groupLines(pieces);
    let pageHeader = findHeader(lines);
    if (pageHeader && header && !sameFields(pageHeader, header)) {
      pageHeader = null; // a summary box ("Debit | Credit | Balance"), not the repeated header
    }
    if (pageHeader) {
      if (!header) {
        rows.push(pageHeader.line.pieces.map((cell) => cell.text));
        rowPages.push(pageNumber);
      }
      header = pageHeader;
    }
    if (!header) continue; // still above the first table
    const { columns, fields } = header;
    const headerY = pageHeader ? pageHeader.line.y : -Infinity;
    const body = lines.filter((line) => line.y > headerY);

    const pitch = median(body.slice(1).map((line, i) => line.y - body[i].y));
    const description = fields.get("description");
    const date = fields.get("date");
    let canJoin = false; // the row above is a transaction (or its continuation)
    let previousY = -Infinity;

    for (const line of body) {
      const cells = cellsOf(line, columns);
      const filled = cells.flatMap((cell, column) => (cell ? [column] : []));
      const wrapped =
        canJoin &&
        description !== undefined &&
        filled.length === 1 &&
        filled[0] === description &&
        line.y - previousY <= WRAP_GAP * pitch;

      if (wrapped) {
        const row = rows[rows.length - 1];
        row[description] = `${row[description]} ${cells[description]}`.trim();
      } else {
        rows.push(cells);
        rowPages.push(pageNumber);
        canJoin = date === undefined || cells[date] !== "";
      }
      previousY = line.y;
    }
  }

  if (!header) throw new NoTableHeader();
  return { rows, pages: rowPages };
}

/** RFC 4180 CSV: fields with a comma, quote, line break or edge space are quoted. */
export function toCsv(rows: string[][]): string {
  const field = (value: string) =>
    /[",\r\n]|^\s|\s$/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
  return rows.map((row) => row.map(field).join(",")).join("\r\n") + "\r\n";
}
