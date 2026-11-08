#!/usr/bin/env bash
# Scores categorisation on the evaluation set and saves the run for the evaluation report.
#
#   bash scripts/categorize-eval.sh LABEL                            # the suggested model
#   bash scripts/categorize-eval.sh LABEL nomic-embed-text:latest    # another model's input
#   CATEGORIZE_EVAL_FINAL=1 bash scripts/categorize-eval.sh LABEL    # also the locked test set
#
# Build a model's input first with scripts/build-categorize-eval.sh. The run is saved as
# backend/ai/eval/results/categorization-LABEL.json (git-ignored), next to the other saved runs.
set -euo pipefail

cd "$(dirname "$0")/.."
label="${1:?give the run a label, like gemma-v1}"
model="${2:-}"
input_env=()
if [ -n "$model" ]; then
    slug="$(echo "${model%:*}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\{1,\}/-/g')"
    input_env=(-e "CATEGORIZE_EVAL_INPUT=/app/.eval-cache/categorize-eval-$slug.json")
fi
target="backend/ai/eval/results/categorization-$label.json"
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
if [ -e "$target" ]; then
    echo "$target exists: pick another label" >&2
    exit 1
fi

# MSYS_NO_PATHCONV: Git Bash on Windows would otherwise rewrite the container paths.
MSYS_NO_PATHCONV=1 docker compose exec -T "${input_env[@]}" \
    -e CATEGORIZE_EVAL_OUT=/app/.eval-cache/categorization.json \
    -e GIT_COMMIT="$(git describe --always --dirty)" \
    -e CATEGORIZE_EVAL_FINAL="${CATEGORIZE_EVAL_FINAL:-}" \
    frontend npx vitest run lib/eval/categorize-benchmark.test.ts > "$log" 2>&1 || {
        cat "$log" >&2
        exit 1
    }

mkdir -p backend/ai/eval/results
# The report expects every saved run to carry its kind and label.
node -e '
const fs = require("fs");
const [source, target, label] = process.argv.slice(1);
const run = JSON.parse(fs.readFileSync(source, "utf-8"));
fs.writeFileSync(target, JSON.stringify({ kind: "categorization", label, saved: new Date().toISOString().slice(0, 19), ...run }, null, 1) + "\n");
fs.unlinkSync(source);
' frontend/.eval-cache/categorization.json "$target" "$label"
echo "Saved $target"
