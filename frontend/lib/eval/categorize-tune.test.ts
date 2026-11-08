// Tunes the categorisation thresholds for one embedding model. Opt-in: it prints the result, and
// a person decides what ships (backend ai/services.py, TUNED_THRESHOLDS).
//
//   CATEGORIZE_TUNE=1 [CATEGORIZE_EVAL_INPUT=<path>] npx vitest run lib/eval/categorize-tune.test.ts

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  type EvalInput,
  type EvalRun,
  intervals,
  isRight,
  type Outcome,
  pairedChange,
  PRECISION_TARGET,
  score,
  summarize,
  tune,
  vectorsOf,
} from "./categorize";

const FIXTURE = fileURLToPath(new URL("../__fixtures__/categorize-eval.json", import.meta.url));

describe.skipIf(!process.env.CATEGORIZE_TUNE)("tuning categorisation thresholds", () => {
  it("prints the tuned thresholds and their cross-validated scores", () => {
    const input: EvalInput = JSON.parse(readFileSync(process.env.CATEGORIZE_EVAL_INPUT ?? FIXTURE, "utf-8"));
    const vectors = vectorsOf(input);
    const tuned = tune(input, vectors);
    const dev = [...tuned.heldOut.keys()];
    const before = new Map<EvalRun, Outcome[]>(dev.map((run) => [run, score(run, vectors, input.model, input.thresholds)]));

    const rows = (m: Map<EvalRun, Outcome[]>, keep: (r: EvalRun) => boolean) =>
      dev.filter(keep).flatMap((run) => m.get(run)!);
    const counts = [...new Set(dev.map((r) => r.examples))].sort((a, b) => a - b);
    const byCount = counts.map((examples) => ({
      examples,
      before: summarize(rows(before, (r) => r.examples === examples)),
      after: summarize(rows(tuned.heldOut, (r) => r.examples === examples)),
    }));
    const all = (m: Map<EvalRun, Outcome[]>) => rows(m, () => true);
    const right = (o: Outcome[]) => o.map((x) => (isRight(x) ? 1 : 0));
    const full = Math.max(...counts);
    const report = {
      model: input.model,
      current: input.thresholds,
      tuned: tuned.thresholds,
      picks: tuned.picks,
      target: PRECISION_TARGET,
      pooled: { before: summarize(all(before)), after: summarize(all(tuned.heldOut)) },
      accuracy_change_pooled: pairedChange(right(all(before)), right(all(tuned.heldOut))),
      with_full_examples: {
        before: intervals(rows(before, (r) => r.examples === full)),
        after: intervals(rows(tuned.heldOut, (r) => r.examples === full)),
      },
      by_examples: byCount,
    };
    console.log(JSON.stringify(report, null, 1));
    expect(tuned.picks).toHaveLength(new Set(dev.map((r) => r.fold)).size);
  });
});
