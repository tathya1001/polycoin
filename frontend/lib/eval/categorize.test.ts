import { describe, expect, it } from "vitest";
import {
  bootstrap,
  choose,
  confusions,
  decodeFloat16,
  isRight,
  type Outcome,
  pairedChange,
  perCategory,
  summarize,
} from "./categorize";

function outcome(truth: string, proposed: string | null): Outcome {
  return { row: `${truth}-${proposed}`, truth, proposed, score: null, margin: null };
}

describe("decodeFloat16", () => {
  it("reads little-endian half floats as the backend writes them", () => {
    // 1.0 = 0x3C00, -2.0 = 0xC000, 0.5 = 0x3800, the smallest subnormal = 0x0001
    const bytes = new Uint8Array([0x00, 0x3c, 0x00, 0xc0, 0x00, 0x38, 0x01, 0x00]);
    const base64 = btoa(String.fromCharCode(...bytes));
    expect(decodeFloat16(base64)).toEqual([1, -2, 0.5, 2 ** -24]);
  });
});

describe("what counts as right", () => {
  it("is the true category proposed, or no proposal for a row that belongs in Others", () => {
    expect(isRight(outcome("Food", "Food"))).toBe(true);
    expect(isRight(outcome("Food", "Bills"))).toBe(false);
    expect(isRight(outcome("Food", null))).toBe(false);
    expect(isRight(outcome("Others", null))).toBe(true);
    expect(isRight(outcome("Others", "Bills"))).toBe(false);
  });
});

describe("summarize", () => {
  const outcomes = [
    outcome("Food", "Food"),
    outcome("Food", "Bills"),
    outcome("Bills", "Bills"),
    outcome("Bills", null),
    outcome("Others", null),
  ];

  it("separates how often it proposes from how often a proposal is right", () => {
    const s = summarize(outcomes);
    expect(s.rows).toBe(5);
    expect(s.coverage).toBe(3 / 5);
    expect(s.precision).toBe(2 / 3);
    expect(s.accuracy).toBe(3 / 5); // two right proposals and the Others row left alone
    expect(s.categorised_recall).toBe(2 / 4);
  });

  it("averages F1 over the real categories, leaving Others out", () => {
    const scores = perCategory(outcomes);
    expect(scores.map((c) => c.category)).toEqual(["Bills", "Food"]);
    const bills = scores[0]; // proposed twice, right once; two true rows, one found
    expect([bills.precision, bills.recall, bills.f1]).toEqual([0.5, 0.5, 0.5]);
    expect(summarize(outcomes).macro_f1).toBeCloseTo((0.5 + 2 / 3) / 2);
  });

  it("is zero, not NaN, when nothing is proposed", () => {
    expect(summarize([outcome("Food", null)]).precision).toBe(0);
  });
});

describe("confusions", () => {
  it("counts wrong proposals by pair, most frequent first", () => {
    const outcomes = [
      outcome("Others", "Bills"),
      outcome("Others", "Bills"),
      outcome("Food", "Groceries"),
      outcome("Food", "Food"),
      outcome("Food", null),
    ];
    expect(confusions(outcomes)).toEqual([
      { truth: "Others", proposed: "Bills", count: 2 },
      { truth: "Food", proposed: "Groceries", count: 1 },
    ]);
  });
});

describe("choose", () => {
  const scored = (truth: string, proposed: string, s: number): Outcome => ({ row: `${truth}${s}`, truth, proposed, score: s, margin: 1 });
  // High scores are right, low ones wrong: a cutoff between them gives full precision.
  const outcomes = [
    scored("Food", "Food", 0.7),
    scored("Bills", "Bills", 0.65),
    scored("Food", "Food", 0.6),
    scored("Food", "Bills", 0.4),
    scored("Bills", "Food", 0.35),
  ];

  it("takes the most coverage that still reaches the precision target", () => {
    const chosen = choose(new Map([["10/0.7", outcomes]]), 0.9);
    expect(chosen.min_score).toBeGreaterThan(0.4);
    expect(chosen.min_score).toBeLessThanOrEqual(0.6);
    expect(chosen).toMatchObject({ blend_full_at: 10, blend_max_weight: 0.7 });
  });

  it("falls back to the most precise setting when no setting reaches the target", () => {
    // Cutoffs up to 0.5 keep all three (1 of 3 right); 0.51-0.6 keeps two (1 of 2); above that,
    // only the wrong one. No cutoff reaches 0.99, so the most precise wins: 1 of 2.
    const mixed = [scored("Food", "Bills", 0.7), scored("Food", "Food", 0.6), scored("Bills", "Food", 0.5)];
    const chosen = choose(new Map([["10/0.7", mixed]]), 0.99);
    expect(chosen.min_score).toBeGreaterThan(0.5);
    expect(chosen.min_score).toBeLessThanOrEqual(0.6);
  });
});

describe("pairedChange", () => {
  it("measures the change on the same rows", () => {
    expect(pairedChange([0, 0, 1], [1, 1, 1])).toEqual([2 / 3, expect.any(Number), expect.any(Number)]);
    expect(() => pairedChange([1], [1, 0])).toThrow();
  });
});

describe("bootstrap", () => {
  it("gives a constant's own value and an interval around a mixed mean, the same every run", () => {
    expect(bootstrap([1, 1, 1])).toEqual([1, 1, 1]);
    const values = [1, 0, 1, 1, 0, 1, 1, 1, 0, 1];
    const [mean, low, high] = bootstrap(values);
    expect(mean).toBeCloseTo(0.7);
    expect(low).toBeLessThan(mean);
    expect(high).toBeGreaterThan(mean);
    expect(bootstrap(values)).toEqual([mean, low, high]);
  });
});
