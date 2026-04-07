#!/usr/bin/env bash
# PutnamBench: (1) dedupe existing Goedel-8B logs, (2) resume whole_proof for missing problems,
# (3) optional SGE second pass (near_miss with baseline sorry proofs on still-incomplete items).
#
# Repo root: Zam/lean
#
# Phase 1 — 补跑缺失题（默认 Goedel-8B, pass@32）:
#   export CUDA_VISIBLE_DEVICES=0,1
#   bash scripts/run_putnam_resume_sge.sh resume
#
# Phase 2 — SGE（在 Phase1 完成并 proof_results 已更新后）:
#   bash scripts/run_putnam_resume_sge.sh sge
#
# Putnam 2025 子集 + Goedel-32B（pass@32），整题 vs 整题+SGE 级联:
#   bash scripts/run_putnam_resume_sge.sh putnam2025-32b
#   bash scripts/run_putnam_resume_sge.sh putnam2025-32b-cascade
#
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${PUTNAM_OUT:-results/prover/putnambench_goedel8b}"
DEDUP="${PUTNAM_DEDUP:-$OUT/proof_results_deduped.json}"
INCOMPLETE_JSONL="${PUTNAM_INCOMPLETE:-$OUT/incomplete_after_baseline.jsonl}"
SGE_OUT="${PUTNAM_SGE_OUT:-results/prover/putnambench_goedel8b_sge2}"

GOEDEL8="${GOEDEL8_MODEL:-Goedel-LM/Goedel-Prover-V2-8B}"
GOEDEL32="${GOEDEL32_MODEL:-Goedel-LM/Goedel-Prover-V2-32B}"
TP8="${TP:-2}"
TP32="${TP32:-2}"
SAMPLES="${SAMPLES:-32}"
MAX_TOK="${MAX_TOK:-8192}"
MAX_ML="${MAX_ML:-16384}"
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"

dedupe_step() {
  mkdir -p "$OUT"
  if [[ ! -f "$OUT/proof_results.json" ]]; then
    echo "Missing $OUT/proof_results.json" >&2
    exit 1
  fi
  python3 scripts/dedupe_proof_results.py "$OUT/proof_results.json" -o "$DEDUP"
  echo "Deduped -> $DEDUP (use as --resume source)"
}

run_resume() {
  dedupe_step
  mkdir -p "$OUT"
  python3 -m prover.run \
    --dataset putnambench \
    --model "$GOEDEL8" \
    --output-dir "$OUT" \
    --strategies whole_proof \
    --samples "$SAMPLES" \
    --tp "$TP8" \
    --max-tokens "$MAX_TOK" \
    --max-model-len "$MAX_ML" \
    --no-chat \
    --resume "$DEDUP" \
    2>&1 | tee -a "$OUT/resume_run.log"
  echo "Done. Merge: cp $OUT/proof_results.json $OUT/proof_results_after_resume.json # backup; dedupe again if needed"
}

run_sge() {
  if [[ ! -f "$OUT/proof_results.json" ]]; then
    echo "Run 'resume' first so $OUT/proof_results.json exists." >&2
    exit 1
  fi
  python3 scripts/dedupe_proof_results.py "$OUT/proof_results.json" -o "$DEDUP"
  python3 scripts/export_putnam_incomplete_jsonl.py \
    --proof-results "$DEDUP" \
    -o "$INCOMPLETE_JSONL"
  local n
  n=$(wc -l < "$INCOMPLETE_JSONL" | tr -d ' ')
  if [[ "$n" -eq 0 ]]; then
    echo "No incomplete problems; skip SGE."
    exit 0
  fi
  mkdir -p "$SGE_OUT"
  python3 -m prover.run \
    --dataset "$(realpath "$INCOMPLETE_JSONL")" \
    --model "$GOEDEL8" \
    --output-dir "$SGE_OUT" \
    --strategies near_miss \
    --samples "$SAMPLES" \
    --near-miss-rounds "${NEAR_MISS_ROUNDS:-8}" \
    --near-miss-samples "${NEAR_MISS_SAMPLES:-8}" \
    --baseline-results "$DEDUP" \
    --tp "$TP8" \
    --max-tokens "$MAX_TOK" \
    --max-model-len "$MAX_ML" \
    --no-chat \
    2>&1 | tee -a "$SGE_OUT/sge_run.log"
  echo "SGE logs: $SGE_OUT/proof_results.json — merge with baseline for reporting (dedupe by problem_id)."
}

run_putnam2025_32b() {
  local mode="${1:-whole}"
  local extra=()
  if [[ "$mode" == "cascade" ]]; then
    extra=(--strategies whole_proof near_miss --cascade)
  else
    extra=(--strategies whole_proof)
  fi
  python3 -m prover.run \
    --dataset putnam_2025 \
    --model "$GOEDEL32" \
    --output-dir results/prover/putnam_2025_32b_${mode} \
    --samples "$SAMPLES" \
    --tp "$TP32" \
    --max-tokens "$MAX_TOK" \
    --max-model-len "$MAX_ML" \
    --no-chat \
    "${extra[@]}" \
    2>&1 | tee -a "results/prover/putnam_2025_32b_${mode}/run.log"
}

case "${1:-help}" in
  dedupe) dedupe_step ;;
  resume) run_resume ;;
  sge) run_sge ;;
  putnam2025-32b) run_putnam2025_32b whole ;;
  putnam2025-32b-cascade) run_putnam2025_32b cascade ;;
  help|*)
    sed -n '2,30p' "$0"
    ;;
esac
