// Categorisation quality on the evaluation set, scored with the production code (lib/scoring.ts).
//
// The input (lib/__fixtures__/categorize-eval.json) holds real prepare_run payloads, one per fold
// and per number of examples the user has given, with every text's vector. Build it with
// scripts/build-categorize-eval.sh. Nothing here runs in the app; tests and scripts only.
//
// A row whose true category is the default ("Others") is uncategorised in the app, so the right
// outcome for it is no proposal. Every other row is right only when its true category is proposed.

import { buildProposals, type Vector } from "@/lib/scoring";
import type { PreparedRun } from "@/lib/types";

export const DEFAULT_CATEGORY = "Others";

export type Thresholds = PreparedRun["thresholds"];
export type EvalRun = {
  split: "dev" | "test";
  fold: number;
  examples: number; // categorised rows per category the user had given
  run: PreparedRun;
  truth: Record<string, string>; // row id -> true category name
};
export type EvalInput = {
  model: string;
  digest: string;
  thresholds: Thresholds;
  runs: EvalRun[];
  vectors: Record<string, string>; // text -> little-endian float16, base64
};
export type Outcome = { row: string; truth: string; proposed: string | null; score: number | null; margin: number | null };

/** IEEE 754 half precision to a number. */
function halfToFloat(bits: number): number {
  const sign = bits & 0x8000 ? -1 : 1;
  const exponent = (bits >> 10) & 0x1f;
  const fraction = bits & 0x3ff;
  if (exponent === 0) return sign * 2 ** -14 * (fraction / 1024);
  if (exponent === 31) return fraction ? NaN : sign * Infinity;
  return sign * 2 ** (exponent - 15) * (1 + fraction / 1024);
}

/** A vector stored as little-endian float16 in base64, as the backend's dataset.encode writes it. */
export function decodeFloat16(base64: string): Vector {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  return Array.from({ length: bytes.length / 2 }, (_, i) => halfToFloat(view.getUint16(i * 2, true)));
}

/** Decodes each distinct text's vector once. */
export function vectorsOf(input: EvalInput): Map<string, Vector> {
  return new Map(Object.entries(input.vectors).map(([text, encoded]) => [text, decodeFloat16(encoded)]));
}

/** One run through the production scoring, with the given thresholds. */
export function score(run: EvalRun, vectors: Map<string, Vector>, model: string, thresholds: Thresholds): Outcome[] {
  const texts = run.run.texts.map((text) => {
    const vector = vectors.get(text);
    if (!vector) throw new Error(`No vector for "${text}": rebuild the evaluation input.`);
    return vector;
  });
  const preview = buildProposals({ ...run.run, thresholds }, texts, model);
  return preview.proposals.map((p) => ({
    row: p.transaction,
    truth: run.truth[p.transaction],
    proposed: p.decision === "propose" ? p.category : null, // ids are category names in this input
    score: p.score,
    margin: p.score !== null && p.runner_up_score !== null ? p.score - p.runner_up_score : null,
  }));
}

export function isRight(o: Outcome): boolean {
  return o.proposed === null ? o.truth === DEFAULT_CATEGORY : o.proposed === o.truth;
}

export type Summary = {
  rows: number;
  proposed: number;
  coverage: number; // share of rows given a proposal
  precision: number; // share of proposals that are right
  accuracy: number; // share of rows that end right (a right proposal, or none for an "Others" row)
  categorised_recall: number; // share of rows outside "Others" that get their category
  macro_f1: number; // mean F1 over the categories other than "Others"
};

export function summarize(outcomes: Outcome[]): Summary {
  const proposed = outcomes.filter((o) => o.proposed !== null);
  const correct = proposed.filter((o) => o.proposed === o.truth).length;
  const categorised = outcomes.filter((o) => o.truth !== DEFAULT_CATEGORY);
  const f1s = perCategory(outcomes).map((c) => c.f1);
  return {
    rows: outcomes.length,
    proposed: proposed.length,
    coverage: ratio(proposed.length, outcomes.length),
    precision: ratio(correct, proposed.length),
    accuracy: ratio(outcomes.filter(isRight).length, outcomes.length),
    categorised_recall: ratio(categorised.filter((o) => o.proposed === o.truth).length, categorised.length),
    macro_f1: f1s.length ? f1s.reduce((a, b) => a + b, 0) / f1s.length : 0,
  };
}

function ratio(part: number, whole: number): number {
  return whole ? part / whole : 0;
}

export type CategoryScore = { category: string; support: number; precision: number; recall: number; f1: number };

export function perCategory(outcomes: Outcome[]): CategoryScore[] {
  const names = [...new Set(outcomes.map((o) => o.truth))].filter((n) => n !== DEFAULT_CATEGORY).sort();
  return names.map((category) => {
    const tp = outcomes.filter((o) => o.proposed === category && o.truth === category).length;
    const proposed = outcomes.filter((o) => o.proposed === category).length;
    const support = outcomes.filter((o) => o.truth === category).length;
    const precision = ratio(tp, proposed);
    const recall = ratio(tp, support);
    const f1 = precision + recall ? (2 * precision * recall) / (precision + recall) : 0;
    return { category, support, precision, recall, f1 };
  });
}

/** The most frequent wrong proposals: (true category, proposed category, count). */
export function confusions(outcomes: Outcome[], top = 5): { truth: string; proposed: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const o of outcomes) {
    if (o.proposed !== null && o.proposed !== o.truth) {
      const key = `${o.truth}\u0000${o.proposed}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([key, count]) => {
      const [truth, proposed] = key.split("\u0000");
      return { truth, proposed, count };
    })
    .sort((a, b) => b.count - a.count || a.truth.localeCompare(b.truth) || a.proposed.localeCompare(b.proposed))
    .slice(0, top);
}

/** A small seeded generator (mulberry32), so a rerun prints the same interval. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The mean of 0/1 or numeric values with its 95% percentile bootstrap interval: [mean, low, high]. */
export function bootstrap(values: number[], resamples = 2000, seed = 2026): [number, number, number] {
  if (values.length === 0) return [0, 0, 0];
  const random = seeded(seed);
  const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const means = Array.from({ length: resamples }, () =>
    mean(Array.from({ length: values.length }, () => values[Math.floor(random() * values.length)])),
  ).sort((a, b) => a - b);
  const at = (q: number) => means[Math.min(resamples - 1, Math.floor(q * resamples))];
  return [mean(values), at(0.025), at(0.975)];
}

/** Every run of one split and example count, pooled: each row is scored once, in its own fold. */
export function pooled(
  input: EvalInput,
  vectors: Map<string, Vector>,
  split: "dev" | "test",
  examples: number,
  thresholds: Thresholds,
): Outcome[] {
  return input.runs
    .filter((r) => r.split === split && r.examples === examples)
    .flatMap((r) => score(r, vectors, input.model, thresholds));
}

// --- Tuning ---------------------------------------------------------------------------------------
// The blend settings change the prototypes, so each blend is scored through buildProposals once.
// min_score and min_margin only decide whether the best category is proposed, so they are applied
// to those scores afterwards, by the same rule as scoring.decide (a test checks they agree).

const steps = (from: number, to: number, step: number) =>
  Array.from({ length: Math.round((to - from) / step) + 1 }, (_, i) => Math.round((from + i * step) * 1000) / 1000);

export const GRID = {
  min_score: steps(0.2, 0.8, 0.01),
  min_margin: [0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15],
  blend_full_at: [5, 10, 20],
  blend_max_weight: [0.5, 0.7, 0.9],
};
export const PRECISION_TARGET = 0.9; // a wrong proposal costs the user more than a skipped one

/** Every target's best category with its score and margin, proposed whatever they are. */
export function unfiltered(run: EvalRun, vectors: Map<string, Vector>, model: string, blend: Pick<Thresholds, "blend_full_at" | "blend_max_weight">): Outcome[] {
  return score(run, vectors, model, { ...blend, min_score: -Infinity, min_margin: -Infinity });
}

/** What scoring.decide would do with these thresholds. */
export function applyThresholds(o: Outcome, minScore: number, minMargin: number): Outcome {
  const passes = o.score !== null && o.score >= minScore && (o.margin === null || o.margin >= minMargin);
  return { ...o, proposed: passes ? o.proposed : null };
}

type Tally = { proposed: number; correct: number; rows: number };

function tally(outcomes: Outcome[], minScore: number, minMargin: number): Tally {
  let proposed = 0;
  let correct = 0;
  for (const o of outcomes) {
    if (o.proposed !== null && o.score !== null && o.score >= minScore && (o.margin === null || o.margin >= minMargin)) {
      proposed += 1;
      if (o.proposed === o.truth) correct += 1;
    }
  }
  return { proposed, correct, rows: outcomes.length };
}

/** True if `a` comes before `b` comparing element by element, larger first. */
function ranksAbove(a: number[], b: number[]): boolean {
  const i = a.findIndex((value, n) => value !== b[n]);
  return i >= 0 && a[i] > b[i];
}

/** The thresholds with the most coverage whose precision reaches the target; if none does, the
 * most precise. Ties go to the higher precision, then the stricter score. */
export function choose(byBlend: Map<string, Outcome[]>, target = PRECISION_TARGET): Thresholds {
  let best: { key: [number, number, number, number]; thresholds: Thresholds } | null = null;
  for (const [blendKey, outcomes] of byBlend) {
    const [blend_full_at, blend_max_weight] = blendKey.split("/").map(Number);
    for (const min_score of GRID.min_score) {
      for (const min_margin of GRID.min_margin) {
        const t = tally(outcomes, min_score, min_margin);
        const precision = t.proposed ? t.correct / t.proposed : 0;
        const coverage = t.proposed / t.rows;
        const key: [number, number, number, number] = [precision >= target ? 1 : 0, precision >= target ? coverage : precision, precision, min_score];
        if (!best || ranksAbove(key, best.key)) {
          best = { key, thresholds: { min_score, min_margin, blend_full_at, blend_max_weight } };
        }
      }
    }
  }
  return best!.thresholds;
}

export const blendKey = (b: Pick<Thresholds, "blend_full_at" | "blend_max_weight">) => `${b.blend_full_at}/${b.blend_max_weight}`;

/** Unfiltered outcomes of the given runs for every blend in the grid. */
export function byBlend(runs: EvalRun[], vectors: Map<string, Vector>, model: string): Map<string, Map<EvalRun, Outcome[]>> {
  const result = new Map<string, Map<EvalRun, Outcome[]>>();
  for (const blend_full_at of GRID.blend_full_at) {
    for (const blend_max_weight of GRID.blend_max_weight) {
      const blend = { blend_full_at, blend_max_weight };
      result.set(blendKey(blend), new Map(runs.map((run) => [run, unfiltered(run, vectors, model, blend)])));
    }
  }
  return result;
}

function pick(all: Map<string, Map<EvalRun, Outcome[]>>, keep: (run: EvalRun) => boolean): Map<string, Outcome[]> {
  return new Map([...all].map(([key, runs]) => [key, [...runs].filter(([run]) => keep(run)).flatMap(([, o]) => o)]));
}

export type Tuned = { thresholds: Thresholds; picks: Thresholds[]; heldOut: Map<EvalRun, Outcome[]> };

/** Thresholds tuned on every dev run, and honest scores: each fold's runs scored with the
 * thresholds tuned on the other folds. */
export function tune(input: EvalInput, vectors: Map<string, Vector>): Tuned {
  const dev = input.runs.filter((r) => r.split === "dev");
  const all = byBlend(dev, vectors, input.model);
  const folds = [...new Set(dev.map((r) => r.fold))].sort((a, b) => a - b);
  const picks: Thresholds[] = [];
  const heldOut = new Map<EvalRun, Outcome[]>();
  for (const fold of folds) {
    const chosen = choose(pick(all, (r) => r.fold !== fold));
    picks.push(chosen);
    const runs = all.get(blendKey(chosen))!;
    for (const [run, outcomes] of runs) {
      if (run.fold === fold) heldOut.set(run, outcomes.map((o) => applyThresholds(o, chosen.min_score, chosen.min_margin)));
    }
  }
  return { thresholds: choose(pick(all, () => true)), picks, heldOut };
}

/** Mean change per row (after - before) with its paired bootstrap interval: [mean, low, high]. */
export function pairedChange(before: number[], after: number[]): [number, number, number] {
  if (before.length !== after.length) throw new Error("paired results must cover the same rows");
  return bootstrap(after.map((value, i) => value - before[i]));
}

export function intervals(outcomes: Outcome[]) {
  const proposed = outcomes.filter((o) => o.proposed !== null);
  return {
    precision: bootstrap(proposed.map((o) => (o.proposed === o.truth ? 1 : 0))),
    coverage: bootstrap(outcomes.map((o) => (o.proposed !== null ? 1 : 0))),
    accuracy: bootstrap(outcomes.map((o) => (isRight(o) ? 1 : 0))),
  };
}
