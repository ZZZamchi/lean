#!/usr/bin/env bash
# minif2f 子问题 MVP：单一入口（子命令）
#
# GPU：请同时设置可见设备列表与张量并行宽度（二者一致）：
#   export CUDA_VISIBLE_DEVICES=2,3,6,7
#   export GPUS=4
# 若未设置 GPUS，则按 CUDA_VISIBLE_DEVICES 中逗号分隔设备数自动推断。
# 若二者都未设置，默认 CUDA_VISIBLE_DEVICES=2,3,6,7、GPUS=4。
#
# failed-only / hybrid-failed-only 编译（默认 32 worker、chunk 512、timeout 300s）：
#   export FAILED_CPU=32 FAILED_CHUNK_SIZE=512 FAILED_COMPILE_TIMEOUT=300
#   export CHUNK_GAP_SEC=15 MEM_DROP_BELOW_GB=0 MEM_WAIT_MAX_SEC=90  # 欲等内存回落可设 MEM_DROP_BELOW_GB
#   export SUBCHUNK_CHUNK_INDEX=0,1 SUBCHUNK_SIZE=8  # 仅当某块 OOM 时对指定块再拆小（compile_by_chunks）
#
# smoke-lift（默认编译 + --reeval-abnormal）：
#   SMOKE_LIFT_N=28 SMOKE_LIFT_CRITERION=lift_sample_fail|fail_all_at_k
#   SMOKE_LIFT_SKIP_COMPILE=1  # 只写 JSON 不跑 Lean
#   SMOKE_LIFT_CPU=8 SMOKE_LIFT_TIMEOUT=240
#
# 用法：
#   bash scripts/minif2f_subproblem_mvp.sh full              # 全流程
#   bash scripts/minif2f_subproblem_mvp.sh analyze           # 失败挖掘 + 结论 md
#   bash scripts/minif2f_subproblem_mvp.sh smoke              # 子题小样本编译自测
#   bash scripts/minif2f_subproblem_mvp.sh failed-only         # 仅 failed-only 合并与报告
#   bash scripts/minif2f_subproblem_mvp.sh mini                # 前 N 行推理+编译+回填（需 GPU）
#   bash scripts/minif2f_subproblem_mvp.sh extend             # 需先 export MVP_DIR=独立目录
#   bash scripts/minif2f_subproblem_mvp.sh resume             # 从 [4/8] 续跑（DeepSeek 已推理完）
#   bash scripts/minif2f_subproblem_mvp.sh resume-goedel      # 从 [5/8] 续跑（DeepSeek 已编译，重做 Goedel）
#   bash scripts/minif2f_subproblem_mvp.sh report-debiased    # 合并 baseline 编译结果去抖动 + mvp_report_debiased.md + flip 诊断
#   bash scripts/minif2f_subproblem_mvp.sh analyze-pass32-fail # 离线：pass@32 全败题 vs 子题 DS/GO 规律 + router 一致性
#   bash scripts/minif2f_subproblem_mvp.sh hybrid-build       # 生成 repaired_from_hybrid.json（跨模型子题选优，零推理）
#   bash scripts/minif2f_subproblem_mvp.sh hybrid-failed-only # hybrid + failed-only 子集编译 + merge + 报告（含 hybrid 列）
#   bash scripts/minif2f_subproblem_mvp.sh smoke-lift        # 小规模 hybrid 验证（见 SMOKE_LIFT_* 环境变量）
#   bash scripts/minif2f_subproblem_mvp.sh recompile-goedel-repaired  # 仅重编 repaired_from_goedel（长时）
#   bash scripts/minif2f_subproblem_mvp.sh help
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mvp_apply_gpu() {
  export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-2,3,6,7}"
  if [[ -z "${GPUS:-}" ]]; then
    GPUS=$(echo "$CUDA_VISIBLE_DEVICES" | awk -F',' '{print NF}')
    export GPUS
  fi
}

mvp_repl_env() {
  export REPL_PEXPECT_MAXREAD="${REPL_PEXPECT_MAXREAD:-8192}"
  export IMPORT_TIMEOUT="${IMPORT_TIMEOUT:-300}"
  export REPL_WATCHDOG_GRACE_SEC="${REPL_WATCHDOG_GRACE_SEC:-8}"
}

# 其他 benchmark（Putnam / FATE 等）：与 minif2f 相同文件布局时可直接改路径，例如
#   export ROUND_DIR=results/putnambench MVP_DIR=results/putnambench/subproblem_mvp
#   bash scripts/minif2f_subproblem_mvp.sh full   # 需已有 to_inference_codes.json + code_compilation_repl.json
#
# Optional flags for minif2f_build_repaired_codes.py / hybrid (export MVP_FILL_ONLY_BASE_ALL_FAIL=1 / MVP_PICK_SHORTEST_PASSING=1 / MVP_HYBRID_SHORTEST_BOTH=1)
mvp_fill_extra_args() {
  MVP_FILL_EXTRA_ARGS=()
  [[ "${MVP_FILL_ONLY_BASE_ALL_FAIL:-}" == 1 ]] && MVP_FILL_EXTRA_ARGS+=(--only_if_base_all_fail_baseline)
  [[ "${MVP_PICK_SHORTEST_PASSING:-}" == 1 ]] && MVP_FILL_EXTRA_ARGS+=(--pick_shortest_passing)
  return 0
}

mvp_hybrid_extra_args() {
  MVP_HYBRID_EXTRA_ARGS=()
  [[ -f "${MVP_DIR}/router_scores.json" ]] && MVP_HYBRID_EXTRA_ARGS+=(--router_scores "${MVP_DIR}/router_scores.json")
  [[ "${MVP_PICK_SHORTEST_PASSING:-}" == 1 ]] && MVP_HYBRID_EXTRA_ARGS+=(--pick_shortest_passing)
  [[ "${MVP_HYBRID_SHORTEST_BOTH:-}" == 1 ]] && MVP_HYBRID_EXTRA_ARGS+=(--pick_shortest_when_both)
  [[ "${MVP_FILL_ONLY_BASE_ALL_FAIL:-}" == 1 ]] && MVP_HYBRID_EXTRA_ARGS+=(--only_if_base_all_fail_baseline)
  return 0
}

mvp_hybrid_build() {
  mvp_hybrid_extra_args
  python3 scripts/minif2f_build_hybrid_repaired_codes.py \
    --input_manifest "${MVP_DIR}/subproblem_manifest_goal.json" \
    --deepseek_sub_compile "${MVP_DIR}/deepseek/code_compilation_repl.json" \
    --goedel_sub_compile "${MVP_DIR}/goedel/code_compilation_repl.json" \
    --input_original_codes "${ORIG_CODES}" \
    --baseline_compile "${ORIG_COMP}" \
    "${MVP_HYBRID_EXTRA_ARGS[@]}" \
    --output_repaired_codes "${MVP_DIR}/repaired_from_hybrid.json"
}

ROUND_DIR="${ROUND_DIR:-results/minif2f/round_2}"
MVP_DIR="${MVP_DIR:-${ROUND_DIR}/subproblem_mvp}"
N_SUBPROBLEMS="${N_SUBPROBLEMS:-400}"
SUBPROBLEM_COMPILE_TIMEOUT="${SUBPROBLEM_COMPILE_TIMEOUT:-450}"
ORIG_CODES="${ROUND_DIR}/to_inference_codes.json"
ORIG_COMP="${ROUND_DIR}/code_compilation_repl.json"
LOG_DIR="${LOG_DIR:-results/logs/minif2f_subproblem_mvp}"
# failed-only / hybrid-failed-only：默认 32 worker、较大分块；OOM 时可 export SUBCHUNK_CHUNK_INDEX=0,1 SUBCHUNK_SIZE=8
# 若 baseline 将大量题标为 abnormal 而跳过编译，指标会与 baseline 完全一致；要强制重编异常题：export MVP_COMPILE_REEVAL_ABNORMAL=1
FAILED_CPU="${FAILED_CPU:-32}"
FAILED_CHUNK_SIZE="${FAILED_CHUNK_SIZE:-512}"
FAILED_COMPILE_TIMEOUT="${FAILED_COMPILE_TIMEOUT:-300}"

mvp_failed_compile_banner() {
  echo "[compile] FAILED_CPU=${FAILED_CPU} FAILED_CHUNK_SIZE=${FAILED_CHUNK_SIZE} FAILED_COMPILE_TIMEOUT=${FAILED_COMPILE_TIMEOUT} CHUNK_GAP_SEC=${CHUNK_GAP_SEC:-15} MEM_DROP_BELOW_GB=${MEM_DROP_BELOW_GB:-0} MEM_WAIT_MAX_SEC=${MEM_WAIT_MAX_SEC:-90} MVP_COMPILE_REEVAL_ABNORMAL=${MVP_COMPILE_REEVAL_ABNORMAL:-0}"
  if command -v free >/dev/null 2>&1; then
    free -h | head -2 || true
  fi
}

mvp_failed_compile_extra() {
  MVP_FAILED_COMPILE_EXTRA=()
  [[ "${MVP_COMPILE_REEVAL_ABNORMAL:-}" == 1 ]] && MVP_FAILED_COMPILE_EXTRA+=(--reeval-abnormal)
  return 0
}

cmd="${1:-help}"
if [[ "$cmd" == help || "$cmd" == -h || "$cmd" == --help ]]; then
  sed -n '2,35p' "$0"
  exit 0
fi
shift || true

case "$cmd" in
  full)
    mvp_apply_gpu
    mvp_repl_env
    mvp_fill_extra_args
    mkdir -p "${MVP_DIR}" "${MVP_DIR}/logs" "${LOG_DIR}"
    MANIFEST_RAW="${MVP_DIR}/subproblem_manifest_raw.json"
    SUB_DS_RAW="${MVP_DIR}/subproblem_dataset_raw.jsonl"
    MANIFEST_GOAL="${MVP_DIR}/subproblem_manifest_goal.json"
    SUB_DS_GOAL="${MVP_DIR}/subproblem_dataset_goal.jsonl"

    echo "[1/8] Extract sorry subproblems..."
    python3 scripts/minif2f_extract_sorry_subproblems.py \
      --input_codes "${ORIG_CODES}" \
      --input_compilation "${ORIG_COMP}" \
      --output_manifest "${MANIFEST_RAW}" \
      --output_dataset_jsonl "${SUB_DS_RAW}"

    echo "[2/8] Extract goal states..."
    python3 scripts/minif2f_extract_goal_states.py \
      --input_manifest "${MANIFEST_RAW}" \
      --output_manifest "${MANIFEST_GOAL}" \
      --output_dataset_jsonl "${SUB_DS_GOAL}" \
      --limit "${N_SUBPROBLEMS}"

    echo "[3/8] DeepSeek inference on subproblems..."
    mkdir -p "${MVP_DIR}/deepseek"
    python3 src/inference.py \
      --input_path "${SUB_DS_GOAL}" \
      --model_path "deepseek-ai/DeepSeek-Prover-V2-7B" \
      --output_dir "${MVP_DIR}/deepseek" \
      --n "${N_SAMPLES_DEEPSEEK:-8}" \
      --gpu "${GPUS}" \
      --inference_handler dpskcot \
      --correction_round 0 \
      --max_model_len "${MAX_MODEL_LEN:-40960}" \
      --temp 1.0 \
      --origin_id_priority leaf

    echo "[4/8] Compile DeepSeek subproblem attempts..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/deepseek/to_inference_codes.json" \
      --output_path "${MVP_DIR}/deepseek/code_compilation_repl.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks

    echo "[5/8] Goedel inference on subproblems..."
    mkdir -p "${MVP_DIR}/goedel"
    python3 src/inference.py \
      --input_path "${SUB_DS_GOAL}" \
      --model_path "Goedel-LM/Goedel-Prover-V2-8B" \
      --output_dir "${MVP_DIR}/goedel" \
      --n "${N_SAMPLES_GOEDEL:-8}" \
      --gpu "${GPUS}" \
      --inference_handler dpskcot \
      --correction_round 0 \
      --max_model_len "${MAX_MODEL_LEN:-40960}" \
      --temp 1.0 \
      --origin_id_priority leaf

    echo "[6/8] Compile Goedel subproblem attempts..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/goedel/to_inference_codes.json" \
      --output_path "${MVP_DIR}/goedel/code_compilation_repl.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks

    echo "[7/8] Build repaired code candidates..."
    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_subproblem_compile "${MVP_DIR}/deepseek/code_compilation_repl.json" \
      --input_original_codes "${ORIG_CODES}" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "${MVP_DIR}/repaired_from_deepseek.json"

    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_subproblem_compile "${MVP_DIR}/goedel/code_compilation_repl.json" \
      --input_original_codes "${ORIG_CODES}" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "${MVP_DIR}/repaired_from_goedel.json"

    echo "[8/9] Compile repaired and compute router coefficients..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_deepseek.json" \
      --output_path "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks

    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_goedel.json" \
      --output_path "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks

    python3 scripts/minif2f_compute_router_scores.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_model_compiles "deepseek=${MVP_DIR}/deepseek/code_compilation_repl.json" "goedel=${MVP_DIR}/goedel/code_compilation_repl.json" \
      --output_json "${MVP_DIR}/router_scores.json"

    echo "[9/9] Build MVP report..."
    python3 scripts/minif2f_report_mvp.py \
      --baseline_compile "${ORIG_COMP}" \
      --deepseek_repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --goedel_repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --output_md "${MVP_DIR}/mvp_report.md"

    echo "Done. Outputs in ${MVP_DIR}"
    ;;

  analyze)
    python3 scripts/minif2f_mine_compilation_failures.py
    python3 scripts/minif2f_analyze_abnormal_attribution.py
    python3 scripts/analyze_subproblem_compile_failures.py
    python3 scripts/minif2f_mvp_experiment_summary.py
    echo "Analysis outputs: results/compilation_failure_mine.json, results/abnormal_attribution_summary.json, ${MVP_DIR}/subproblem_compile_failure_analysis.json, ${MVP_DIR}/mvp_experiment_conclusion.md"
    ;;

  analyze-pass32-fail)
    for need in "${ORIG_COMP}" "${MVP_DIR}/subproblem_manifest_goal.json" \
      "${MVP_DIR}/deepseek/code_compilation_repl.json" "${MVP_DIR}/goedel/code_compilation_repl.json"; do
      if [[ ! -f "$need" ]]; then
        echo "Missing $need"
        exit 1
      fi
    done
    RS_ARGS=()
    [[ -f "${MVP_DIR}/router_scores.json" ]] && RS_ARGS+=(--router_scores "${MVP_DIR}/router_scores.json")
    python3 scripts/minif2f_analyze_pass32_fail_patterns.py \
      --baseline_compile "${ORIG_COMP}" \
      --input_manifest "${MVP_DIR}/subproblem_manifest_goal.json" \
      --deepseek_sub_compile "${MVP_DIR}/deepseek/code_compilation_repl.json" \
      --goedel_sub_compile "${MVP_DIR}/goedel/code_compilation_repl.json" \
      "${RS_ARGS[@]}" \
      --output_md "${MVP_DIR}/pass32_fail_patterns.md" \
      --output_json "${MVP_DIR}/pass32_fail_patterns.json"
    ;;

  smoke-lift)
    mvp_repl_env
    SL_ARGS=(
      python3 scripts/minif2f_subproblem_smoke_lift.py
      --round_dir "${ROUND_DIR}"
      --mvp_dir "${MVP_DIR}"
      --n_problems "${SMOKE_LIFT_N:-20}"
      --criterion "${SMOKE_LIFT_CRITERION:-lift_sample_fail}"
      --compile_cpu "${SMOKE_LIFT_CPU:-8}"
      --compile_timeout "${SMOKE_LIFT_TIMEOUT:-240}"
    )
    [[ "${SMOKE_LIFT_SKIP_COMPILE:-}" != 1 ]] && SL_ARGS+=(--run_compile --reeval_abnormal)
    "${SL_ARGS[@]}"
    ;;

  hybrid-build)
    for need in "${ORIG_COMP}" "${ORIG_CODES}" "${MVP_DIR}/subproblem_manifest_goal.json" \
      "${MVP_DIR}/deepseek/code_compilation_repl.json" "${MVP_DIR}/goedel/code_compilation_repl.json"; do
      if [[ ! -f "$need" ]]; then
        echo "Missing $need"
        exit 1
      fi
    done
    mvp_hybrid_build
    ;;

  hybrid-failed-only)
    for need in "${MVP_DIR}/repaired_from_deepseek_compiled_merged.json" "${MVP_DIR}/repaired_from_goedel_compiled_merged.json"; do
      if [[ ! -f "$need" ]]; then
        echo "Missing $need — run: bash scripts/minif2f_subproblem_mvp.sh failed-only"
        exit 1
      fi
    done
    mvp_repl_env
    export CHUNK_GAP_SEC="${CHUNK_GAP_SEC:-15}"
    LOG="${LOG:-${LOG_DIR}/hybrid_failed_only_compile.log}"
    LOCKDIR="${LOCKDIR:-${LOG_DIR}/.hybrid_failed_only_compile.lockdir}"
    mkdir -p "${LOG_DIR}"
    if ! mkdir "$LOCKDIR" 2>/dev/null; then
      echo "Another hybrid-failed-only run (lock: $LOCKDIR). Exit."
      exit 0
    fi
    cleanup() { rm -rf "$LOCKDIR" 2>/dev/null || true; }
    trap cleanup EXIT
    {
      echo "=== $(date -Is) hybrid-failed-only ==="
      mvp_failed_compile_banner
      mvp_failed_compile_extra
      mvp_hybrid_build
      python3 scripts/minif2f_filter_codes_failed_problems_only.py \
        --baseline_compile "${ORIG_COMP}" \
        --input_codes "${MVP_DIR}/repaired_from_hybrid.json" \
        --output_codes "${MVP_DIR}/repaired_from_hybrid_failed_only.json"
      python3 scripts/compile_by_chunks.py \
        --input_path "${MVP_DIR}/repaired_from_hybrid_failed_only.json" \
        --output_path "${MVP_DIR}/repaired_from_hybrid_failed_only_compiled.json" \
        --chunk_size "${FAILED_CHUNK_SIZE}" --cpu "${FAILED_CPU}" --timeout "${FAILED_COMPILE_TIMEOUT}" --keep_chunks --force \
        "${MVP_FAILED_COMPILE_EXTRA[@]}"
      python3 scripts/minif2f_merge_compile_subset_into_baseline.py \
        --baseline_compile "${ORIG_COMP}" \
        --subset_compile "${MVP_DIR}/repaired_from_hybrid_failed_only_compiled.json" \
        --output "${MVP_DIR}/repaired_from_hybrid_compiled_merged.json"
      python3 scripts/minif2f_compute_router_scores.py \
        --input_manifest "${MVP_DIR}/subproblem_manifest_goal.json" \
        --input_model_compiles \
          "deepseek=${MVP_DIR}/deepseek/code_compilation_repl.json" \
          "goedel=${MVP_DIR}/goedel/code_compilation_repl.json" \
        --output_json "${MVP_DIR}/router_scores.json"
      python3 scripts/minif2f_report_mvp.py \
        --baseline_compile "${ORIG_COMP}" \
        --deepseek_repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled_merged.json" \
        --goedel_repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled_merged.json" \
        --hybrid_repaired_compile "${MVP_DIR}/repaired_from_hybrid_compiled_merged.json" \
        --output_md "${MVP_DIR}/mvp_report.md"
      python3 scripts/minif2f_mvp_experiment_summary.py
      echo "=== $(date -Is) hybrid-failed-only done ==="
    } 2>&1 | tee -a "$LOG"
    ;;

  smoke)
    mvp_repl_env
    SMOKE_DIR="${SMOKE_DIR:-${ROUND_DIR}/subproblem_mvp_smoke}"
    SRC_INF="${SUBPROBLEM_INFERENCE_JSON:-${MVP_DIR}/deepseek/to_inference_codes.json}"
    SMOKE_ROWS="${SMOKE_ROWS:-2}"
    if [[ ! -f "$SRC_INF" ]]; then
      echo "Missing $SRC_INF — run full or mini first, or set SUBPROBLEM_INFERENCE_JSON"
      exit 1
    fi
    mkdir -p "$SMOKE_DIR"
    export SRC_INF SMOKE_DIR SMOKE_ROWS
    python3 << 'PY'
import json, os
from pathlib import Path
src = Path(os.environ["SRC_INF"])
n = int(os.environ["SMOKE_ROWS"])
rows = json.loads(src.read_text(encoding="utf-8"))
out = Path(os.environ["SMOKE_DIR"]) / "to_inference_codes.json"
out.write_text(json.dumps(rows[:n], ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {len(rows[:n])} rows -> {out}")
PY
    OUT_COMP="${SMOKE_DIR}/code_compilation_repl.json"
    python3 scripts/compile_by_chunks.py \
      --input_path "${SMOKE_DIR}/to_inference_codes.json" \
      --output_path "${OUT_COMP}" \
      --chunk_size "${SMOKE_ROWS}" \
      --cpu "${SMOKE_CPU:-2}" \
      --timeout "${SMOKE_TIMEOUT:-300}" \
      --keep_chunks \
      --reeval-abnormal \
      --force
    python3 << PY
import json
from pathlib import Path
p = Path("${OUT_COMP}")
rows = json.loads(p.read_text(encoding="utf-8"))
ok = sum(1 for r in rows if (r.get("compilation_result") or {}).get("pass"))
print(f"Smoke compile: {ok}/{len(rows)} passed -> {p}")
PY
    ;;

  failed-only)
    mvp_repl_env
    export CHUNK_GAP_SEC="${CHUNK_GAP_SEC:-15}"
    LOG="${LOG:-${LOG_DIR}/pipeline_continue.log}"
    LOCKDIR="${LOCKDIR:-${LOG_DIR}/.failed_only_compile.lockdir}"
    mkdir -p "${LOG_DIR}"
    if ! mkdir "$LOCKDIR" 2>/dev/null; then
      echo "Another failed-only run (lock: $LOCKDIR). Exit."
      exit 0
    fi
    cleanup() { rm -rf "$LOCKDIR" 2>/dev/null || true; }
    trap cleanup EXIT
    {
      echo "=== $(date -Is) failed-only ==="
      mvp_failed_compile_banner
      mvp_failed_compile_extra
      python3 scripts/compile_by_chunks.py \
        --input_path "${MVP_DIR}/repaired_from_deepseek_failed_only.json" \
        --output_path "${MVP_DIR}/repaired_from_deepseek_failed_only_compiled.json" \
        --chunk_size "${FAILED_CHUNK_SIZE}" --cpu "${FAILED_CPU}" --timeout "${FAILED_COMPILE_TIMEOUT}" --keep_chunks --force \
        "${MVP_FAILED_COMPILE_EXTRA[@]}"
      python3 scripts/compile_by_chunks.py \
        --input_path "${MVP_DIR}/repaired_from_goedel_failed_only.json" \
        --output_path "${MVP_DIR}/repaired_from_goedel_failed_only_compiled.json" \
        --chunk_size "${FAILED_CHUNK_SIZE}" --cpu "${FAILED_CPU}" --timeout "${FAILED_COMPILE_TIMEOUT}" --keep_chunks --force \
        "${MVP_FAILED_COMPILE_EXTRA[@]}"
      python3 scripts/minif2f_merge_compile_subset_into_baseline.py \
        --baseline_compile "${ORIG_COMP}" \
        --subset_compile "${MVP_DIR}/repaired_from_deepseek_failed_only_compiled.json" \
        --output "${MVP_DIR}/repaired_from_deepseek_compiled_merged.json"
      python3 scripts/minif2f_merge_compile_subset_into_baseline.py \
        --baseline_compile "${ORIG_COMP}" \
        --subset_compile "${MVP_DIR}/repaired_from_goedel_failed_only_compiled.json" \
        --output "${MVP_DIR}/repaired_from_goedel_compiled_merged.json"
      python3 scripts/minif2f_compute_router_scores.py \
        --input_manifest "${MVP_DIR}/subproblem_manifest_goal.json" \
        --input_model_compiles \
          "deepseek=${MVP_DIR}/deepseek/code_compilation_repl.json" \
          "goedel=${MVP_DIR}/goedel/code_compilation_repl.json" \
        --output_json "${MVP_DIR}/router_scores.json"
      python3 scripts/minif2f_report_mvp.py \
        --baseline_compile "${ORIG_COMP}" \
        --deepseek_repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled_merged.json" \
        --goedel_repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled_merged.json" \
        --output_md "${MVP_DIR}/mvp_report.md"
      python3 scripts/minif2f_mvp_experiment_summary.py
      echo "=== $(date -Is) failed-only done ==="
    } 2>&1 | tee -a "$LOG"
    ;;

  mini)
    mvp_apply_gpu
    mvp_repl_env
    mvp_fill_extra_args
    N_LINES="${N_LINES:-5}"
    MINI_DIR="${MINI_DIR:-${MVP_DIR}/_mini_infer}"
    SRC_JSONL="${SUB_DS_GOAL:-${MVP_DIR}/subproblem_dataset_goal.jsonl}"
    MODEL="${MODEL:-deepseek}"
    N_SAMPLES="${N_SAMPLES:-2}"
    if [[ ! -f "$SRC_JSONL" ]]; then
      echo "Missing $SRC_JSONL"
      exit 1
    fi
    mkdir -p "$MINI_DIR"
    head -n "$N_LINES" "$SRC_JSONL" > "${MINI_DIR}/subproblem_dataset_goal.jsonl"
    if [[ "$MODEL" == "goedel" ]]; then
      MPATH="${MODEL_PATH:-Goedel-LM/Goedel-Prover-V2-8B}"
      OUT_SUB="${MINI_DIR}/goedel"
    else
      MPATH="${MODEL_PATH:-deepseek-ai/DeepSeek-Prover-V2-7B}"
      OUT_SUB="${MINI_DIR}/deepseek"
    fi
    mkdir -p "$OUT_SUB"
    python3 src/inference.py \
      --input_path "${MINI_DIR}/subproblem_dataset_goal.jsonl" \
      --model_path "$MPATH" \
      --output_dir "$OUT_SUB" \
      --n "$N_SAMPLES" \
      --gpu "$GPUS" \
      --inference_handler dpskcot \
      --correction_round 0 \
      --max_model_len "${MAX_MODEL_LEN:-40960}" \
      --temp 1.0 \
      --origin_id_priority leaf
    python3 scripts/compile_by_chunks.py \
      --input_path "${OUT_SUB}/to_inference_codes.json" \
      --output_path "${OUT_SUB}/code_compilation_repl.json" \
      --chunk_size 64 \
      --cpu "${CPUS:-4}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --reeval-abnormal \
      --force
    MANIFEST="${MVP_DIR}/subproblem_manifest_goal.json"
    OUT_REP="${MINI_DIR}/repaired_from_${MODEL}.json"
    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "$MANIFEST" \
      --input_subproblem_compile "${OUT_SUB}/code_compilation_repl.json" \
      --input_original_codes "$ORIG_CODES" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "$OUT_REP"
    python3 scripts/analyze_subproblem_compile_failures.py \
      --mvp_dir "$MINI_DIR" \
      --output_json "${MINI_DIR}/subproblem_compile_failure_analysis.json"
    echo "Mini done: $MINI_DIR"
    ;;

  resume)
    mvp_apply_gpu
    mvp_repl_env
    mvp_fill_extra_args
    mkdir -p "${MVP_DIR}" "${LOG_DIR}"
    MANIFEST_GOAL="${MVP_DIR}/subproblem_manifest_goal.json"
    SUB_DS_GOAL="${MVP_DIR}/subproblem_dataset_goal.jsonl"
    if [[ ! -f "${MVP_DIR}/deepseek/to_inference_codes.json" ]]; then
      echo "Missing ${MVP_DIR}/deepseek/to_inference_codes.json — run full or [3/8] first."
      exit 1
    fi
    if [[ ! -f "$SUB_DS_GOAL" ]] || [[ ! -f "$MANIFEST_GOAL" ]]; then
      echo "Missing manifest or goal jsonl."
      exit 1
    fi

    echo "[4/8] Compile DeepSeek subproblem attempts (--force)..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/deepseek/to_inference_codes.json" \
      --output_path "${MVP_DIR}/deepseek/code_compilation_repl.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    echo "[5/8] Goedel inference on subproblems..."
    mkdir -p "${MVP_DIR}/goedel"
    python3 src/inference.py \
      --input_path "${SUB_DS_GOAL}" \
      --model_path "Goedel-LM/Goedel-Prover-V2-8B" \
      --output_dir "${MVP_DIR}/goedel" \
      --n "${N_SAMPLES_GOEDEL:-8}" \
      --gpu "${GPUS}" \
      --inference_handler dpskcot \
      --correction_round 0 \
      --max_model_len "${MAX_MODEL_LEN:-40960}" \
      --temp 1.0 \
      --origin_id_priority leaf

    echo "[6/8] Compile Goedel subproblem attempts..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/goedel/to_inference_codes.json" \
      --output_path "${MVP_DIR}/goedel/code_compilation_repl.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    echo "[7/8] Build repaired code candidates..."
    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_subproblem_compile "${MVP_DIR}/deepseek/code_compilation_repl.json" \
      --input_original_codes "${ORIG_CODES}" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "${MVP_DIR}/repaired_from_deepseek.json"

    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_subproblem_compile "${MVP_DIR}/goedel/code_compilation_repl.json" \
      --input_original_codes "${ORIG_CODES}" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "${MVP_DIR}/repaired_from_goedel.json"

    echo "[8/9] Compile repaired and compute router coefficients..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_deepseek.json" \
      --output_path "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_goedel.json" \
      --output_path "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    python3 scripts/minif2f_compute_router_scores.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_model_compiles "deepseek=${MVP_DIR}/deepseek/code_compilation_repl.json" "goedel=${MVP_DIR}/goedel/code_compilation_repl.json" \
      --output_json "${MVP_DIR}/router_scores.json"

    echo "[9/9] Build MVP report..."
    python3 scripts/minif2f_report_mvp.py \
      --baseline_compile "${ORIG_COMP}" \
      --deepseek_repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --goedel_repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --output_md "${MVP_DIR}/mvp_report.md"

    python3 scripts/minif2f_mvp_experiment_summary.py
    echo "Resume done. Outputs in ${MVP_DIR}"
    ;;

  resume-goedel)
    mvp_apply_gpu
    mvp_repl_env
    mvp_fill_extra_args
    export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"
    export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.78}"
    mkdir -p "${MVP_DIR}" "${LOG_DIR}"
    MANIFEST_GOAL="${MVP_DIR}/subproblem_manifest_goal.json"
    SUB_DS_GOAL="${MVP_DIR}/subproblem_dataset_goal.jsonl"
    if [[ ! -f "${MVP_DIR}/deepseek/code_compilation_repl.json" ]]; then
      echo "Missing ${MVP_DIR}/deepseek/code_compilation_repl.json — run resume or [4/8] first."
      exit 1
    fi
    if [[ ! -f "$SUB_DS_GOAL" ]] || [[ ! -f "$MANIFEST_GOAL" ]]; then
      echo "Missing manifest or goal jsonl."
      exit 1
    fi

    echo "[5/8] Goedel inference on subproblems..."
    mkdir -p "${MVP_DIR}/goedel"
    python3 src/inference.py \
      --input_path "${SUB_DS_GOAL}" \
      --model_path "Goedel-LM/Goedel-Prover-V2-8B" \
      --output_dir "${MVP_DIR}/goedel" \
      --n "${N_SAMPLES_GOEDEL:-8}" \
      --gpu "${GPUS}" \
      --inference_handler dpskcot \
      --correction_round 0 \
      --max_model_len "${MAX_MODEL_LEN:-40960}" \
      --temp 1.0 \
      --origin_id_priority leaf

    echo "[6/8] Compile Goedel subproblem attempts..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/goedel/to_inference_codes.json" \
      --output_path "${MVP_DIR}/goedel/code_compilation_repl.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    echo "[7/8] Build repaired code candidates..."
    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_subproblem_compile "${MVP_DIR}/deepseek/code_compilation_repl.json" \
      --input_original_codes "${ORIG_CODES}" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "${MVP_DIR}/repaired_from_deepseek.json"

    python3 scripts/minif2f_build_repaired_codes.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_subproblem_compile "${MVP_DIR}/goedel/code_compilation_repl.json" \
      --input_original_codes "${ORIG_CODES}" \
      --baseline_compile "${ORIG_COMP}" \
      "${MVP_FILL_EXTRA_ARGS[@]}" \
      --output_repaired_codes "${MVP_DIR}/repaired_from_goedel.json"

    echo "[8/9] Compile repaired and compute router coefficients..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_deepseek.json" \
      --output_path "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_goedel.json" \
      --output_path "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force

    python3 scripts/minif2f_compute_router_scores.py \
      --input_manifest "${MANIFEST_GOAL}" \
      --input_model_compiles "deepseek=${MVP_DIR}/deepseek/code_compilation_repl.json" "goedel=${MVP_DIR}/goedel/code_compilation_repl.json" \
      --output_json "${MVP_DIR}/router_scores.json"

    echo "[9/9] Build MVP report..."
    python3 scripts/minif2f_report_mvp.py \
      --baseline_compile "${ORIG_COMP}" \
      --deepseek_repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --goedel_repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --output_md "${MVP_DIR}/mvp_report.md"

    python3 scripts/minif2f_mvp_experiment_summary.py
    echo "Resume-goedel done. Outputs in ${MVP_DIR}"
    ;;

  recompile-goedel-repaired)
    mvp_repl_env
    mkdir -p "${MVP_DIR}" "${LOG_DIR}"
    if [[ ! -f "${MVP_DIR}/repaired_from_goedel.json" ]]; then
      echo "Missing ${MVP_DIR}/repaired_from_goedel.json"
      exit 1
    fi
    echo "Recompiling repaired_from_goedel.json (long run)..."
    python3 scripts/compile_by_chunks.py \
      --input_path "${MVP_DIR}/repaired_from_goedel.json" \
      --output_path "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --chunk_size 128 \
      --cpu "${CPUS:-16}" \
      --timeout "${SUBPROBLEM_COMPILE_TIMEOUT}" \
      --keep_chunks \
      --force
    echo "Then run: bash scripts/minif2f_subproblem_mvp.sh report-debiased"
    ;;

  report-debiased)
    mvp_repl_env
    mkdir -p "${MVP_DIR}" "${LOG_DIR}"
    for need in "${ORIG_COMP}" "${ORIG_CODES}" \
      "${MVP_DIR}/repaired_from_deepseek.json" \
      "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      "${MVP_DIR}/repaired_from_goedel.json" \
      "${MVP_DIR}/repaired_from_goedel_compiled.json"; do
      if [[ ! -f "$need" ]]; then
        echo "Missing $need"
        exit 1
      fi
    done
    echo "Merge debiased compile (unchanged full_code uses baseline compilation_result)..."
    python3 scripts/minif2f_merge_compile_debiased.py \
      --baseline_compile "${ORIG_COMP}" \
      --original_codes "${ORIG_CODES}" \
      --repaired_codes "${MVP_DIR}/repaired_from_deepseek.json" \
      --repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled.json" \
      --output "${MVP_DIR}/repaired_from_deepseek_compiled_debiased.json"
    python3 scripts/minif2f_merge_compile_debiased.py \
      --baseline_compile "${ORIG_COMP}" \
      --original_codes "${ORIG_CODES}" \
      --repaired_codes "${MVP_DIR}/repaired_from_goedel.json" \
      --repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled.json" \
      --output "${MVP_DIR}/repaired_from_goedel_compiled_debiased.json"
    HY_DEB=()
    if [[ -f "${MVP_DIR}/repaired_from_hybrid.json" && -f "${MVP_DIR}/repaired_from_hybrid_compiled.json" ]]; then
      python3 scripts/minif2f_merge_compile_debiased.py \
        --baseline_compile "${ORIG_COMP}" \
        --original_codes "${ORIG_CODES}" \
        --repaired_codes "${MVP_DIR}/repaired_from_hybrid.json" \
        --repaired_compile "${MVP_DIR}/repaired_from_hybrid_compiled.json" \
        --output "${MVP_DIR}/repaired_from_hybrid_compiled_debiased.json"
      HY_DEB=(--hybrid_repaired_compile "${MVP_DIR}/repaired_from_hybrid_compiled_debiased.json")
    fi
    python3 scripts/minif2f_report_mvp.py \
      --baseline_compile "${ORIG_COMP}" \
      --deepseek_repaired_compile "${MVP_DIR}/repaired_from_deepseek_compiled_debiased.json" \
      --goedel_repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled_debiased.json" \
      "${HY_DEB[@]}" \
      --output_md "${MVP_DIR}/mvp_report_debiased.md"
    echo "Compile flip diagnostic (raw Goedel recompile vs baseline)..."
    python3 scripts/minif2f_diagnose_compile_flip.py \
      --baseline_compile "${ORIG_COMP}" \
      --original_codes "${ORIG_CODES}" \
      --repaired_codes "${MVP_DIR}/repaired_from_goedel.json" \
      --repaired_compile "${MVP_DIR}/repaired_from_goedel_compiled.json"
    echo "Wrote ${MVP_DIR}/mvp_report_debiased.md"
    ;;

  extend)
    if [[ -z "${MVP_DIR:-}" ]]; then
      echo "export MVP_DIR=results/minif2f/round_2/subproblem_mvp_ablation  # 独立目录再跑 full"
      exit 1
    fi
    export ROUND_DIR
    exec bash "$ROOT/scripts/minif2f_subproblem_mvp.sh" full
    ;;

  *)
    echo "Unknown command: $cmd. Use: bash scripts/minif2f_subproblem_mvp.sh help"
    exit 1
    ;;
esac
