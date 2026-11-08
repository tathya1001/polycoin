#!/usr/bin/env bash
# The LLM judge: scores the labelled answers with each judge model, then reports how far each one
# agrees with your labels: on the tuning sheet (dev-docs/phase-13-judge-labels.md, items L..,
# which judge prompts may be tuned on) and on the held-out sheet
# (dev-docs/phase-13-judge-heldout.md, items H.., which they never are).
#
#   bash scripts/judge.sh                           # qwen2.5:7b, prompts v3 and v4 and their average
#   bash scripts/judge.sh --all                     # also every other answer in the run (slow)
#   JUDGES=qwen2.5:7b PROMPT=v1 RUN=llama-json-v2 bash scripts/judge.sh
#
# Scores are cached per model and prompt, so after you edit labels, run it again: no model is
# called, and the agreement is recomputed in seconds. Each judge model is unloaded from Ollama
# after use.
set -euo pipefail

cd "$(dirname "$0")/.."
sheets=(dev-docs/phase-13-judge-labels.md dev-docs/phase-13-judge-heldout.md)
run="${RUN:-llama-text-v2}"
prompt="${PROMPT:-v3,v4}"  # several: each answer is also scored by their average
judges="${JUDGES:-qwen2.5:7b}"
scope="--labelled"
if [ "${1:-}" = "--all" ]; then
    scope=""
fi
ollama="${OLLAMA_HOST_URL:-http://localhost:11434}"

for model in $judges; do
    for one in ${prompt//,/ }; do
        cat "${sheets[@]}" | docker compose exec -T backend python manage.py judge_run \
            --model "$model" --run "$run" --prompt "$one" $scope
    done
    curl -s "$ollama/api/generate" -d "{\"model\":\"$model\",\"keep_alive\":0}" > /dev/null
done

cat "${sheets[@]}" | docker compose exec -T -e GIT_COMMIT="$(git describe --always --dirty)" \
    backend python manage.py judge_report --run "$run" --models "$(echo $judges | tr ' ' ',')" \
    --prompt "$prompt" --record "$run-${prompt//,/-}"
