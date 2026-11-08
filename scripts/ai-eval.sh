#!/usr/bin/env bash
# Builds the AI evaluation report at dev-docs/ai-evaluation.md (private: dev-docs is git-ignored).
#
#   bash scripts/ai-eval.sh                    # search scored now, plus every saved run
#   bash scripts/ai-eval.sh --compare dev-v2   # with before and after against a saved run
#   bash scripts/ai-eval.sh --final            # also the locked test set: once, after all tuning
#
# Needs the Docker Compose stack running (docker compose up -d). Needs no model.
set -euo pipefail

cd "$(dirname "$0")/.."
output="dev-docs/ai-evaluation.md"
partial="$(mktemp)"
trap 'rm -f "$partial"' EXIT

# The containers have no .git folder, so the commit is passed in.
commit="$(git describe --always --dirty)"

mkdir -p dev-docs
docker compose exec -T -e GIT_COMMIT="$commit" backend \
    python manage.py ai_eval_report "$@" > "$partial"
mv "$partial" "$output"
echo "Wrote $output"
