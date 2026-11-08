// Categorisation quality with the suggested embedding model: CI's gate, and the numbers for the
// evaluation report. Scores the committed input (lib/__fixtures__/categorize-eval.json) with the
// production scoring and the server's current thresholds.
//
//   CATEGORIZE_EVAL_INPUT=<path>  score another model's input (from scripts/build-categorize-eval.sh)
//   CATEGORIZE_EVAL_OUT=<path>    also write the results file the report reads (scripts/categorize-eval.sh)
//   CATEGORIZE_EVAL_FINAL=1       also score the locked test set: once, after all tuning

import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  applyThresholds,
  confusions,
  type EvalInput,
  intervals,
  perCategory,
  pooled,
  score,
  summarize,
  unfiltered,
  vectorsOf,
} from "./categorize";

const FIXTURE = fileURLToPath(new URL("../__fixtures__/categorize-eval.json", import.meta.url));
const input: EvalInput = JSON.parse(readFileSync(process.env.CATEGORIZE_EVAL_INPUT ?? FIXTURE, "utf-8"));
const vectors = vectorsOf(input);
const FULL = Math.max(...input.runs.map((r) => r.examples)); // the server's cap per category

// The suggested model's scores at the server's thresholds when this gate was set, rounded down:
// a drop fails, an improvement passes.
const FLOOR = { precision: 0.937, coverage: 0.719 };

describe("categorisation on the evaluation set", () => {
  const production = pooled(input, vectors, "dev", FULL, input.thresholds);
  const summary = summarize(production);

  // The floor belongs to the committed input (the suggested model); another model's is only scored.
  it.skipIf(Boolean(process.env.CATEGORIZE_EVAL_INPUT))("keeps its precision and coverage with the user's examples", () => {
    expect(summary.precision).toBeGreaterThanOrEqual(FLOOR.precision);
    expect(summary.coverage).toBeGreaterThanOrEqual(FLOOR.coverage);
  });

  it("tunes with the same decision rule the app uses", () => {
    // Tuning applies min_score and min_margin to unfiltered scores; that must match scoring.decide.
    const runs = input.runs.filter((r) => r.split === "dev" && r.fold === 0);
    for (const [minScore, minMargin] of [[0.3, 0], [0.4, 0.05], [0.5, 0.1], [0.34, 0.08]]) {
      for (const run of runs) {
        const thresholds = { ...input.thresholds, min_score: minScore, min_margin: minMargin };
        const direct = score(run, vectors, input.model, thresholds).map((o) => o.proposed);
        const applied = unfiltered(run, vectors, input.model, thresholds).map(
          (o) => applyThresholds(o, minScore, minMargin).proposed,
        );
        expect(applied).toEqual(direct);
      }
    }
  });

  it("scores every dev row once per example count", () => {
    const rows = new Set(input.runs.filter((r) => r.split === "dev").flatMap((r) => Object.keys(r.truth)));
    const counts = [...new Set(input.runs.filter((r) => r.split === "dev").map((r) => r.examples))];
    for (const examples of counts) {
      expect(pooled(input, vectors, "dev", examples, input.thresholds)).toHaveLength(rows.size);
    }
  });

  it("writes the results file when asked", () => {
    const out = process.env.CATEGORIZE_EVAL_OUT;
    if (!out) return;
    const counts = [...new Set(input.runs.filter((r) => r.split === "dev").map((r) => r.examples))].sort((a, b) => a - b);
    const curve = counts.map((examples) => ({
      examples,
      ...summarize(pooled(input, vectors, "dev", examples, input.thresholds)),
    }));
    const results: Record<string, unknown> = {
      meta: {
        date: new Date().toISOString().slice(0, 10),
        commit: process.env.GIT_COMMIT ?? "unknown",
        model: input.model,
        digest: input.digest,
        thresholds: input.thresholds,
      },
      headline: {
        model: input.model,
        precision: summary.precision,
        coverage: summary.coverage,
        accuracy: summary.accuracy,
        "macro F1": summary.macro_f1,
        "precision, no examples": curve[0].precision,
        "coverage, no examples": curve[0].coverage,
      },
      production: { ...summary, intervals: intervals(production) },
      curve,
      per_category: perCategory(production),
      confusions: confusions(production),
    };
    if (process.env.CATEGORIZE_EVAL_FINAL) {
      const held = pooled(input, vectors, "test", FULL, input.thresholds);
      results.final = { ...summarize(held), intervals: intervals(held) };
    }
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, JSON.stringify(results, null, 1) + "\n");
    console.log(JSON.stringify({ curve, production: results.production, confusions: results.confusions }, null, 1));
  });
});
