#!/usr/bin/env bash
# Goedel-Prover-V2-8B whole_proof runs on non-miniF2F datasets (extend cross-bench coverage).
# Priority: ProofNet, FATE-X, full FATE-M (150), optional FATE-H re-run.
#
# Usage (repo root /home/.../Zam/lean):
#   export CUDA_VISIBLE_DEVICES=0,1   # or 6,7 etc.
#   bash scripts/run_goedel8b_cross_benchmarks.sh proofnet
#   bash scripts/run_goedel8b_cross_benchmarks.sh fate_x
#   bash scripts/run_goedel8b_cross_benchmarks.sh fate_m
#   bash scripts/run_goedel8b_cross_benchmarks.sh fate_h
#   bash scripts/run_goedel8b_cross_benchmarks.sh all
#
# Resume: re-run the same command; prover merges existing proof_results.json when --resume is passed.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${GOEDEL_MODEL:-Goedel-LM/Goedel-Prover-V2-8B}"
TP="${TP:-2}"
SAMPLES="${SAMPLES:-32}"
MAX_TOK="${MAX_TOK:-8192}"
MAX_ML="${MAX_ML:-16384}"
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"

run_one() {
  local dataset="$1"
  local out="$2"
  shift 2
  local extra=("$@")
  local resume=()
  if [[ -f "$out/proof_results.json" ]]; then
    resume=(--resume "$out/proof_results.json")
    echo "Resuming $dataset -> $out"
  fi
  mkdir -p "$out"
  python3 -m prover.run \
    --dataset "$dataset" \
    --model "$MODEL" \
    --output-dir "$out" \
    --strategies whole_proof \
    --samples "$SAMPLES" \
    --tp "$TP" \
    --max-tokens "$MAX_TOK" \
    --max-model-len "$MAX_ML" \
    --no-chat \
    "${resume[@]}" \
    "${extra[@]}" \
    2>&1 | tee -a "$out/run.log"
}

case "${1:-help}" in
  proofnet)
    run_one proofnet results/prover/proofnet_goedel8b
    ;;
  fate_x)
    run_one fate_x results/prover/fate_x_goedel8b
    ;;
  fate_m)
    run_one fate_m results/prover/fate_m_goedel8b_full150
    ;;
  fate_h)
    run_one fate_h results/prover/fate_h_goedel8b_rerun
    ;;
  all)
    run_one proofnet results/prover/proofnet_goedel8b
    run_one fate_x results/prover/fate_x_goedel8b
    run_one fate_m results/prover/fate_m_goedel8b_full150
    run_one fate_h results/prover/fate_h_goedel8b_rerun
    ;;
  help|-h|--help)
    sed -n '2,18p' "$0"
    exit 0
    ;;
  *)
    echo "Unknown target: $1"; exit 1
    ;;
esac
