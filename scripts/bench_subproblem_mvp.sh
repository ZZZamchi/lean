#!/usr/bin/env bash
# Putnam / FATE 等：离线潜力扫描 + 子题 sorry 抽取（与 minif2f MVP 同一套 Python，零 GPU）
#
#   bash scripts/bench_subproblem_mvp.sh scan-all
#   bash scripts/bench_subproblem_mvp.sh extract-putnam     # MAX_SUBPROBLEMS 默认 600
#   bash scripts/bench_subproblem_mvp.sh extract-fate-ds
#   bash scripts/bench_subproblem_mvp.sh extract-fate-go
#   bash scripts/bench_subproblem_mvp.sh stats        # 打印已生成的 manifest 行数
#   bash scripts/bench_subproblem_mvp.sh help
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd="${1:-help}"
MAX_SUBPROBLEMS="${MAX_SUBPROBLEMS:-600}"

case "$cmd" in
  help|-h|--help)
    sed -n '2,11p' "$0"
    exit 0
    ;;

  scan-all)
    for p in putnambench fate_deepseek fate_goedel minif2f_round_2; do
      echo "=== bench_subproblem_lift_scan: $p ==="
      python3 scripts/bench_subproblem_lift_scan.py --preset "$p"
    done
    python3 scripts/bench_subproblem_lift_scan.py --preset fate_deepseek \
      --cross_compile results/fate_h_goedel_gpu67/code_compilation_repl.json \
      --label fate_cross_ds_vs_go \
      --out_json results/fate_h_deepseek_gpu12/subproblem_lift_scan_cross_go.json
    echo "Done. See results/*/subproblem_lift_scan.json"
    ;;

  extract-putnam)
    OUT="${PUTNAM_SUBPROBLEM_DIR:-results/putnambench/subproblem_mvp}"
    mkdir -p "$OUT"
    python3 scripts/minif2f_extract_sorry_subproblems.py \
      --input_codes results/putnambench/to_inference_codes.json \
      --input_compilation results/putnambench/code_compilation_repl.json \
      --output_manifest "${OUT}/subproblem_manifest_raw.json" \
      --output_dataset_jsonl "${OUT}/subproblem_dataset_raw.jsonl" \
      --use_not_complete_as_fail \
      --dedupe_problem_base \
      --max_subproblems "${MAX_SUBPROBLEMS}"
    echo "Wrote ${OUT}/subproblem_manifest_raw.json (cap ${MAX_SUBPROBLEMS}, dedupe by base, incomplete-as-fail)"
    ;;

  extract-fate-ds)
    OUT="${FATE_SUBPROBLEM_DIR:-results/fate_h_deepseek_gpu12/subproblem_mvp}"
    mkdir -p "$OUT"
    python3 scripts/minif2f_extract_sorry_subproblems.py \
      --input_codes results/fate_h_deepseek_gpu12/to_inference_codes.json \
      --input_compilation results/fate_h_deepseek_gpu12/code_compilation_repl.json \
      --output_manifest "${OUT}/subproblem_manifest_raw.json" \
      --output_dataset_jsonl "${OUT}/subproblem_dataset_raw.jsonl" \
      --use_not_complete_as_fail \
      --dedupe_problem_base \
      --max_subproblems "${MAX_SUBPROBLEMS}"
    echo "Wrote ${OUT}/subproblem_manifest_raw.json"
    ;;

  stats)
    python3 << 'PY'
import json
from pathlib import Path
root = Path("results")
paths = [
    root / "putnambench/subproblem_mvp/subproblem_manifest_raw.json",
    root / "fate_h_deepseek_gpu12/subproblem_mvp/subproblem_manifest_raw.json",
    root / "fate_h_goedel_gpu67/subproblem_mvp/subproblem_manifest_raw.json",
]
for p in paths:
    if not p.is_file():
        print(f"{p}: (missing)")
        continue
    n = len(json.loads(p.read_text(encoding="utf-8")))
    print(f"{p}: {n} subproblems")
PY
    ;;

  extract-fate-go)
    OUT="${FATE_SUBPROBLEM_DIR:-results/fate_h_goedel_gpu67/subproblem_mvp}"
    mkdir -p "$OUT"
    python3 scripts/minif2f_extract_sorry_subproblems.py \
      --input_codes results/fate_h_goedel_gpu67/to_inference_codes.json \
      --input_compilation results/fate_h_goedel_gpu67/code_compilation_repl.json \
      --output_manifest "${OUT}/subproblem_manifest_raw.json" \
      --output_dataset_jsonl "${OUT}/subproblem_dataset_raw.jsonl" \
      --use_not_complete_as_fail \
      --dedupe_problem_base \
      --max_subproblems "${MAX_SUBPROBLEMS}"
    echo "Wrote ${OUT}/subproblem_manifest_raw.json"
    ;;

  *)
    echo "Unknown: $cmd"; sed -n '2,11p' "$0"; exit 1
    ;;
esac
