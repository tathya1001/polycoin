import { describe, expect, it } from "vitest";
import fixtures from "./__fixtures__/scoring-cases.json";
import { buildPrototype, buildProposals, cosineSimilarities, decide, normalize, type Vector } from "./scoring";
import type { PreparedRun } from "./types";

// Same float64 maths as numpy, summed in a different order: agreement to ~1e-15 is expected.
const DIGITS = 12;

function expectVector(actual: number[], expected: number[]) {
  expect(actual).toHaveLength(expected.length);
  actual.forEach((x, i) => expect(x).toBeCloseTo(expected[i], DIGITS));
}

function expectScore(actual: number | null, expected: number | null) {
  if (expected === null) expect(actual).toBeNull();
  else expect(actual).toBeCloseTo(expected, DIGITS);
}

// --- parity with the original Python scoring (lib/__fixtures__/scoring-cases.json) ---

describe("matches the Python scoring it replaces", () => {
  it.each(fixtures.normalize)("normalize #%#", ({ vector, expected }) => {
    expectVector(normalize(vector), expected);
  });

  it.each(fixtures.cosine)("cosineSimilarities #%#", ({ vector, matrix, expected }) => {
    expectVector(cosineSimilarities(vector, matrix), expected);
  });

  it.each(fixtures.prototype)("buildPrototype #%#", ({ label, examples, full_at, max_weight, expected }) => {
    expectVector(buildPrototype(label, examples, full_at, max_weight), expected);
  });

  it.each(fixtures.decide)("decide: $name", ({ vector, prototypes, min_score, min_margin, expected }) => {
    const result = decide(vector, prototypes as [string, Vector][], min_score, min_margin);

    expect([result.category, result.runnerUp, result.decision]).toEqual([
      expected.category,
      expected.runner_up,
      expected.decision,
    ]);
    expectScore(result.score, expected.score);
    expectScore(result.runnerUpScore, expected.runner_up_score);
  });

  it.each(fixtures.runs)("buildProposals: $name", ({ run, vectors, expected }) => {
    const preview = buildProposals(run as unknown as PreparedRun, vectors, "some-model");

    expect(preview.proposals).toHaveLength(expected.length);
    preview.proposals.forEach((row, i) => {
      const { score, runner_up_score, ...exact } = expected[i];
      expect(row).toMatchObject(exact);
      expectScore(row.score, score);
      expectScore(row.runner_up_score, runner_up_score);
    });
  });
});

// --- the same rules the original Python unit tests stated, directly ---

describe("normalize", () => {
  it("gives unit length", () => {
    expectVector(normalize([3, 4]), [0.6, 0.8]);
  });

  it("leaves a zero vector alone", () => {
    expect(normalize([0, 0])).toEqual([0, 0]);
  });

  it("does not change its input", () => {
    const input = [3, 4];
    normalize(input);
    expect(input).toEqual([3, 4]);
  });
});

describe("cosineSimilarities", () => {
  it("is 1 for the same direction, 0 for orthogonal, and ignores scale", () => {
    expectVector(cosineSimilarities([1, 0], [[1, 0], [0, 1], [5, 0]]), [1, 0, 1]);
  });

  it("rejects vectors of different sizes", () => {
    expect(() => cosineSimilarities([1, 0], [[1, 0, 0]])).toThrow("different dimensions");
  });
});

describe("buildPrototype", () => {
  it("is just the label without examples", () => {
    expect(buildPrototype([1, 0], [], 10, 0.7)).toEqual([1, 0]);
  });

  it.each([
    [5, 0.35], // half-way
    [10, 0.7], // full
    [50, 0.7], // capped
  ])("blends %i examples with weight %f", (count, weight) => {
    const examples = Array.from({ length: count }, () => [0, 1]);
    expectVector(buildPrototype([1, 0], examples, 10, 0.7), normalize([1 - weight, weight]));
  });
});

describe("decide", () => {
  const protos: [string, Vector][] = [
    ["a", [1, 0]],
    ["b", [0, 1]],
  ];

  it("proposes a clear winner", () => {
    const result = decide([1, 0.1], protos, 0.5, 0.05);
    expect([result.category, result.runnerUp, result.decision]).toEqual(["a", "b", "propose"]);
  });

  it("rejects a low score on its own", () => {
    const opposite: [string, Vector][] = [
      ["a", normalize([1, -1])],
      ["b", normalize([-1, 1])],
    ];
    expect(decide([1, 1], opposite, 0.5, 0).decision).toBe("below_threshold");
  });

  it("rejects a narrow margin on its own", () => {
    expect(decide([1, 1], protos, 0.5, 0.05).decision).toBe("too_close");
  });

  it("skips the margin check with one candidate", () => {
    const result = decide([1, 0], [protos[0]], 0.5, 0.9);
    expect([result.runnerUp, result.runnerUpScore, result.decision]).toEqual([null, null, "propose"]);
  });

  it("has nothing to propose without candidates", () => {
    expect(decide([1, 0], [], 0.5, 0.05).decision).toBe("no_candidates");
  });

  it("breaks ties by candidate order", () => {
    const result = decide([1, 1], [["z", [1, 0]], ["y", [0, 1]]], 0.1, 0);
    expect(result.category).toBe("z");
  });
});

describe("buildProposals", () => {
  const run: PreparedRun = {
    considered: 3,
    capped: true,
    thresholds: { min_score: 0.5, min_margin: 0.05, blend_full_at: 10, blend_max_weight: 0.7 },
    texts: ["Food", "Salary", "lunch", "payroll"],
    candidates: { debit: [{ category: "food", name: "Food", label: 0, examples: [] }] },
    targets: [
      { transaction: "t1", date: "2026-01-01", txn_type: "debit", name: "Cafe", amount: "5.00", text: 2 },
      { transaction: "t2", date: "2026-01-02", txn_type: "credit", name: "Acme", amount: "9.00", text: 3 },
    ],
  };
  const vectors = [[1, 0], [0, 1], [1, 0.1], [0, 1]];

  it("returns the preview shape the review table already uses", () => {
    const preview = buildProposals(run, vectors, "nomic-embed-text");

    expect(preview).toMatchObject({ model: "nomic-embed-text", considered: 3, proposed: 1, skipped: 2, capped: true });
    expect(preview.proposals[0]).toMatchObject({
      transaction: "t1",
      category: "food",
      category_name: "Food",
      runner_up: null,
      runner_up_name: null,
      decision: "propose",
    });
  });

  it("gives a direction with no candidates nothing to propose", () => {
    const credit = buildProposals(run, vectors, "m").proposals[1];
    expect([credit.category, credit.category_name, credit.decision]).toEqual([null, null, "no_candidates"]);
  });
});
