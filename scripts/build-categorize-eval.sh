#!/usr/bin/env bash
# Builds the categorisation evaluation input for one embedding model, where the frontend reads it.
#
#   bash scripts/build-categorize-eval.sh                            # the suggested model: committed
#   bash scripts/build-categorize-eval.sh nomic-embed-text:latest    # another one: git-ignored cache
#
# Needs the Docker Compose stack and a local Ollama with the model installed. It builds on the test
# database (a throwaway user), so nothing is written to the development database.
set -euo pipefail

cd "$(dirname "$0")/.."
default="embeddinggemma:latest"
model="${1:-$default}"
slug="$(echo "${model%:*}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\{1,\}/-/g')"
if [ "$model" = "$default" ]; then
    output="frontend/lib/__fixtures__/categorize-eval.json"
else
    mkdir -p frontend/.eval-cache
    output="frontend/.eval-cache/categorize-eval-$slug.json"
fi
built="backend/ai/eval/.cache/categorize-eval-$slug.json"  # git-ignored, visible to both sides

# MSYS_NO_PATHCONV: Git Bash on Windows would otherwise rewrite the container path into a Windows one.
MSYS_NO_PATHCONV=1 docker compose exec -T -e CATEGORIZE_EVAL_BUILD=1 -e CATEGORIZE_EVAL_MODEL="$model" \
    -e CATEGORIZE_EVAL_OUT="/app/ai/eval/.cache/categorize-eval-$slug.json" \
    backend pytest ai/test_categorize_eval_build.py -k real -q -s -p no:cacheprovider
mv "$built" "$output"
echo "Wrote $output ($(wc -c < "$output") bytes)"
