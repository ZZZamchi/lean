#!/usr/bin/env bash
# P1 minimal ablation on first 10 unsolved39 problems (dataset/minif2f_ablation_slice10.jsonl).
# Requires free GPUs. Each block writes to results/experiments/<dir>.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GPUS="${GPUS:-0,1}"

run() {
  local out="$1"; shift
  python3 experiments/phase1_official_config.py --gpus "$GPUS" \
    --dataset minif2f_ablation_slice10 --output-dir "$out" \
    --samples 16 --self-correction 2 "$@"
}

# Baseline: chat + 32K tokens (official-style)
run "ablation_slice10_chat_32k" --max-tokens 32768

# Chat off (same tokens)
run "ablation_slice10_nochat_32k" --max-tokens 32768 --no-chat

# Shorter context (ablation): 4K tokens, chat on
run "ablation_slice10_chat_4k" --max-tokens 4096 --max-model-len 8192

echo "Done. Summarize:"
echo "  python3 scripts/summarize_experiment_dirs.py"
