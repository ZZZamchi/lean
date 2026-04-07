#!/usr/bin/env bash
# P0-3: Self-correction 0 vs 2 rounds on the same 10-problem slice (GPU required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GPUS="${GPUS:-0,1}"

python3 experiments/phase1_official_config.py --gpus "$GPUS" \
  --dataset minif2f_ablation_slice10 \
  --output-dir ablation_sc0_slice10 \
  --samples 16 --self-correction 0 --max-tokens 32768

python3 experiments/phase1_official_config.py --gpus "$GPUS" \
  --dataset minif2f_ablation_slice10 \
  --output-dir ablation_sc2_slice10 \
  --samples 16 --self-correction 2 --max-tokens 32768

echo "Compare:"
echo "  python3 scripts/compare_phase1_runs.py \\"
echo "    results/experiments/ablation_sc0_slice10/proof_results.json \\"
echo "    results/experiments/ablation_sc2_slice10/proof_results.json"
