// Scores a prepared run in the browser. Ported one-to-one from the backend's original numpy
// scoring (float64, removed once this replaced it); lib/__fixtures__/scoring-cases.json holds
// that code's outputs, and the tests require these functions to reproduce them.

import type { CategorizePreview, PreparedRun, Proposal, ProposalDecision } from "@/lib/types";

export type Vector = number[];

function length(vector: Vector): number {
  let sum = 0;
  for (const x of vector) sum += x * x;
  return Math.sqrt(sum);
}

/** Scale to unit length, so only direction counts. A zero vector stays zero. */
export function normalize(vector: Vector): Vector {
  const size = length(vector) || 1;
  return vector.map((x) => x / size);
}

/** Cosine similarity of `vector` against every row of `matrix`. Vectors from different models
 * live in unrelated spaces, so a size mismatch throws instead of returning a meaningless number. */
export function cosineSimilarities(vector: Vector, matrix: Vector[]): number[] {
  const unit = normalize(vector);
  return matrix.map((row) => {
    if (row.length !== unit.length) throw new Error("Vectors have different dimensions.");
    const unitRow = normalize(row);
    let dot = 0;
    for (let i = 0; i < unit.length; i++) dot += unitRow[i] * unit[i];
    return dot;
  });
}

/** One vector for a category: its label, pulled toward the centroid of the user's own examples.
 * The pull grows with the number of examples and stops at `maxWeight` once there are `fullAt`. */
export function buildPrototype(label: Vector, examples: Vector[], fullAt: number, maxWeight: number): Vector {
  const unitLabel = normalize(label);
  if (examples.length === 0) return unitLabel;

  const weight = (Math.min(examples.length, fullAt) / fullAt) * maxWeight;
  const sum = unitLabel.map(() => 0);
  for (const example of examples) {
    normalize(example).forEach((x, i) => (sum[i] += x));
  }
  const center = normalize(sum.map((x) => x / examples.length));
  return normalize(unitLabel.map((x, i) => (1 - weight) * x + weight * center[i]));
}

export type Decision = {
  category: string | null;
  score: number | null;
  runnerUp: string | null;
  runnerUpScore: number | null;
  decision: ProposalDecision;
};

/** The nearest prototype, but only a proposal if it clears `minScore` and beats the runner-up by
 * `minMargin`. `prototypes` keeps its order: on a tie the earlier candidate wins. */
export function decide(
  vector: Vector,
  prototypes: [string, Vector][],
  minScore: number,
  minMargin: number,
): Decision {
  if (prototypes.length === 0) {
    return { category: null, score: null, runnerUp: null, runnerUpScore: null, decision: "no_candidates" };
  }

  const scores = cosineSimilarities(vector, prototypes.map(([, prototype]) => prototype));
  // Array.prototype.sort is stable, so equal scores keep the candidates' own order.
  const order = scores.map((_, i) => i).sort((a, b) => scores[b] - scores[a]);
  const [best, runner] = order;
  const bestScore = scores[best];
  const runnerScore = runner === undefined ? null : scores[runner];

  let decision: ProposalDecision = "propose";
  if (bestScore < minScore) decision = "below_threshold";
  else if (runnerScore !== null && bestScore - runnerScore < minMargin) decision = "too_close";

  return {
    category: prototypes[best][0],
    score: bestScore,
    runnerUp: runner === undefined ? null : prototypes[runner][0],
    runnerUpScore: runnerScore,
    decision,
  };
}

/** Turn a prepared run and one vector per text into the same preview the server used to send. */
export function buildProposals(run: PreparedRun, vectors: Vector[], model: string): CategorizePreview {
  const { min_score, min_margin, blend_full_at, blend_max_weight } = run.thresholds;
  const names = new Map<string, string>();
  const prototypes: Partial<Record<string, [string, Vector][]>> = {};

  for (const [txnType, candidates] of Object.entries(run.candidates)) {
    prototypes[txnType] = (candidates ?? []).map((c) => {
      names.set(c.category, c.name);
      const examples = c.examples.map((i) => vectors[i]);
      return [c.category, buildPrototype(vectors[c.label], examples, blend_full_at, blend_max_weight)];
    });
  }

  const proposals: Proposal[] = run.targets.map((target) => {
    const d = decide(vectors[target.text], prototypes[target.txn_type] ?? [], min_score, min_margin);
    return {
      transaction: target.transaction,
      date: target.date,
      txn_type: target.txn_type,
      name: target.name,
      amount: target.amount,
      category: d.category,
      category_name: d.category ? (names.get(d.category) ?? null) : null,
      score: d.score,
      runner_up: d.runnerUp,
      runner_up_name: d.runnerUp ? (names.get(d.runnerUp) ?? null) : null,
      runner_up_score: d.runnerUpScore,
      decision: d.decision,
    };
  });

  const proposed = proposals.filter((p) => p.decision === "propose").length;
  return {
    model,
    considered: run.considered,
    proposed,
    skipped: run.considered - proposed,
    capped: run.capped,
    proposals,
  };
}
