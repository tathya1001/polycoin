import { describe, expect, it } from "vitest";
import { buildTable, NoTableHeader, normalise, toCsv, type TextPiece } from "./pdfTable";

// A fake statement page: 9-unit text, 5 units per character, 12 units between lines.
const HEIGHT = 9;
const CHAR = 5;
const PITCH = 12;

function at(text: string, x0: number, y: number): TextPiece {
  return { text, x0, x1: x0 + text.length * CHAR, y, height: HEIGHT };
}

/** Right-aligned text ending at x1, as statements print amounts. */
function right(text: string, x1: number, y: number): TextPiece {
  return at(text, x1 - text.length * CHAR, y);
}

// Date | Narration | Withdrawal Amt. | Deposit Amt. | Closing Balance
function header(y: number): TextPiece[] {
  return [
    at("Date", 40, y),
    at("Narration", 110, y),
    at("Withdrawal", 330, y),
    at("Amt.", 383, y), // one normal space after "Withdrawal": the same cell
    at("Deposit Amt.", 420, y),
    at("Closing Balance", 500, y),
  ];
}

function txn(y: number, date: string, narration: string, debit: string, credit: string, balance: string) {
  return [
    at(date, 40, y),
    at(narration, 110, y),
    ...(debit ? [right(debit, 400, y)] : []),
    ...(credit ? [right(credit, 480, y)] : []),
    right(balance, 575, y),
  ];
}

const HEADER_ROW = ["Date", "Narration", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"];

describe("buildTable", () => {
  it("drops the preamble and puts right-aligned amounts under their headers", () => {
    const page = [
      at("Example Bank", 40, 20),
      at("Statement for Test Person", 40, 32),
      ...header(60),
      ...txn(72, "01/04/2026", "UPI/TASTYBITES", "250.00", "", "9,750.00"),
      ...txn(84, "02/04/2026", "NEFT ACME LTD", "", "5,000.00", "14,750.00"),
    ];

    const table = buildTable([page]);

    expect(table.rows).toEqual([
      HEADER_ROW,
      ["01/04/2026", "UPI/TASTYBITES", "250.00", "", "9,750.00"],
      ["02/04/2026", "NEFT ACME LTD", "", "5,000.00", "14,750.00"],
    ]);
    expect(table.pages).toEqual([1, 1, 1]);
  });

  it("finds the header whatever order the text arrives in", () => {
    const page = [...txn(72, "01/04/2026", "COFFEE", "10.00", "", "990.00"), ...header(60)].reverse();
    expect(buildTable([page]).rows[1]).toEqual(["01/04/2026", "COFFEE", "10.00", "", "990.00"]);
  });

  it("joins a narration that wraps onto the next line", () => {
    const page = [
      ...header(60),
      ...txn(72, "01/04/2026", "UPI/DR/412345678901/TASTY", "250.00", "", "9,750.00"),
      at("BITES CAFE/TSTB", 110, 72 + PITCH),
      at("x@tstb", 110, 72 + 2 * PITCH),
      ...txn(72 + 3 * PITCH, "02/04/2026", "ATM WDL", "100.00", "", "9,650.00"),
    ];

    const { rows } = buildTable([page]);

    expect(rows[1][1]).toBe("UPI/DR/412345678901/TASTY BITES CAFE/TSTB x@tstb");
    expect(rows).toHaveLength(3);
  });

  it("does not join a footer that sits well below the table", () => {
    const page = [
      ...header(60),
      ...txn(72, "01/04/2026", "COFFEE", "10.00", "", "990.00"),
      ...txn(84, "02/04/2026", "TEA", "5.00", "", "985.00"),
      at("Computer generated statement", 110, 84 + 5 * PITCH),
    ];

    const { rows } = buildTable([page]);

    expect(rows[2][1]).toBe("TEA");
    expect(rows[3]).toEqual(["", "Computer generated statement", "", "", ""]); // the server skips it
  });

  it("does not join text under a row that has no date", () => {
    const page = [
      ...header(60),
      at("Opening Balance", 110, 72),
      right("1,000.00", 575, 72),
      at("brought forward", 110, 84),
    ];
    expect(buildTable([page]).rows.slice(1).map((row) => row[1])).toEqual(["Opening Balance", "brought forward"]);
  });

  it("drops a header repeated on later pages and records each row's page", () => {
    const first = [...header(60), ...txn(72, "01/04/2026", "COFFEE", "10.00", "", "990.00")];
    const second = [
      at("Page 2", 40, 20),
      ...header(60),
      ...txn(72, "02/04/2026", "TEA", "5.00", "", "985.00"),
    ];
    const third = [...txn(30, "03/04/2026", "LUNCH", "20.00", "", "965.00")]; // no header: same columns

    const table = buildTable([first, second, third]);

    expect(table.rows.map((row) => row[1])).toEqual(["Narration", "COFFEE", "TEA", "LUNCH"]);
    expect(table.pages).toEqual([1, 1, 2, 3]);
  });

  it("does not mistake a summary box for a repeated header", () => {
    const first = [...header(60), ...txn(72, "01/04/2026", "COFFEE", "10.00", "", "990.00")];
    const last = [
      ...txn(30, "02/04/2026", "TEA", "5.00", "", "985.00"),
      at("Debit", 330, 80),
      at("Credit", 420, 80),
      at("Balance", 500, 80),
    ];

    const { rows } = buildTable([first, last]);

    expect(rows.map((row) => row[1])).toContain("TEA"); // not dropped as "above the header"
  });

  it("ignores pages before the first header", () => {
    const cover = [at("Example Bank", 40, 20), at("Account summary", 40, 40)];
    const page = [...header(60), ...txn(72, "01/04/2026", "COFFEE", "10.00", "", "990.00")];
    expect(buildTable([cover, page]).pages).toEqual([2, 2]);
  });

  it("joins pieces split inside a word without adding a space", () => {
    const page = [
      ...header(60),
      at("01/04/2026", 40, 72),
      at("TASTY", 110, 72),
      at("BITES", 135, 72), // touches "TASTY": one word drawn in two runs
      at("CAFE", 165, 72), // a visible gap: a new word
      right("250.00", 400, 72),
      right("9,750.00", 575, 72),
    ];
    expect(buildTable([page]).rows[1][1]).toBe("TASTYBITES CAFE");
  });

  it("throws when no page has a header", () => {
    const page = [at("01/04/2026", 40, 72), at("COFFEE", 110, 72), right("10.00", 400, 72)];
    expect(() => buildTable([page])).toThrow(NoTableHeader);
  });
});

describe("toCsv", () => {
  it("quotes only the fields that need it", () => {
    expect(toCsv([["Date", "Narration"], ["01/04/2026", 'CAFE, "THE" ONE'], ["", "line\nbreak"]])).toBe(
      'Date,Narration\r\n01/04/2026,"CAFE, ""THE"" ONE"\r\n,"line\nbreak"\r\n',
    );
  });
});

describe("normalise", () => {
  it("matches the server's header normalisation", () => {
    expect(normalise("Withdrawal Amt.")).toBe("withdrawal amt");
    expect(normalise("  Chq./Ref.No. ")).toBe("chq ref no");
  });
});
