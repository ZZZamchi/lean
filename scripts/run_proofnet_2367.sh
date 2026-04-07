#!/usr/bin/env bash
# Proofnet：推理 3 轮（round0/corr1/corr2）取平均 Pass@32，分块编译。
# 默认：GPU 1,2,3,7（4 张）、编译 32 workers、chunk 1000。每轮推理后立即编译（round1/2 依赖前轮编译结果）。
# 时间估计：3 轮推理 ~1.5–2 天（4 卡）；3 轮编译 chunk=1000 ~0.5–1 天；合计约 2–3 天。
# 用法: bash scripts/run_proofnet_2367.sh
# 可选: INFERENCE_ONLY=1 仅推理；COMPILE_ONLY=1 仅编译（需已有 to_inference_codes*.json）
set -e
cd "$(dirname "$0")/.."

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1,2,3,7}"
export GPUS="${GPUS:-4}"
export NUM_SAMPLES_INITIAL=32
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"
OUT_DIR="results/proofnet"
mkdir -p results/logs/proofnet

CPU="${CPU:-32}"
CHUNK_SIZE="${CHUNK_SIZE:-1000}"
TIMEOUT="${TIMEOUT:-450}"
MODEL_PATH="${MODEL_PATH:-Goedel-LM/Goedel-Prover-V2-8B}"
INFERENCE_HANDLER="${INFERENCE_HANDLER:-dpskcot}"
NUM_SAMPLES_CORRECTION=2
TEMPERATURE=1.0
MAX_MODEL_LEN=40960

# 单轮编译（带内存监控，上限 500GB；调用 run_compile_32_with_memory_guard）
_compile_round() {
  local suffix="$1"
  local in_path="$OUT_DIR/to_inference_codes${suffix}.json"
  if [[ ! -f "$in_path" ]]; then
    echo "[proofnet] Skip compile: $in_path not found."
    return 0
  fi
  echo "[proofnet] Compiling round${suffix:-0} (chunk_size=$CHUNK_SIZE, cpu=$CPU, timeout=${TIMEOUT}s, memory threshold 500GB)..."
  COMPILE_BENCH=proofnet PROOFNET_ROUND_SUFFIX="$suffix" MEM_THRESHOLD_GB=500 CPU="$CPU" CHUNK_SIZE="$CHUNK_SIZE" TIMEOUT="$TIMEOUT" \
    bash scripts/run_compile_32_with_memory_guard.sh
}

if [[ "${COMPILE_ONLY:-0}" -eq 0 ]]; then
  # Round 0: 推理
  echo "========== Round 0: Inference (32 samples/problem, GPUs ${CUDA_VISIBLE_DEVICES}) =========="
  MAX_CORRECTION_ROUNDS=0 bash scripts/pipeline.sh --benchmark proofnet --output-dir "$OUT_DIR" --inference-only
fi

if [[ "${INFERENCE_ONLY:-0}" -eq 0 ]]; then
  _compile_round ""
fi

if [[ "${COMPILE_ONLY:-0}" -eq 0 ]] && [[ "${INFERENCE_ONLY:-0}" -eq 0 ]]; then
  # Round 1: 推理（依赖 round0 的 code_compilation_repl.json）
  echo "========== Round 1: Inference (correction, n=$NUM_SAMPLES_CORRECTION) =========="
  python3 src/inference.py \
    --model_path "$MODEL_PATH" \
    --output_dir "$OUT_DIR" \
    --n "$NUM_SAMPLES_CORRECTION" \
    --gpu "$GPUS" \
    --inference_handler "$INFERENCE_HANDLER" \
    --correction_round 1 \
    --previous_run_output_dir "$OUT_DIR" \
    --max_model_len "$MAX_MODEL_LEN" \
    --temp "$TEMPERATURE"
fi

if [[ "${INFERENCE_ONLY:-0}" -eq 0 ]]; then
  _compile_round "_corr1"
fi

if [[ "${COMPILE_ONLY:-0}" -eq 0 ]] && [[ "${INFERENCE_ONLY:-0}" -eq 0 ]]; then
  # Round 2: 推理
  echo "========== Round 2: Inference (correction, n=$NUM_SAMPLES_CORRECTION) =========="
  python3 src/inference.py \
    --model_path "$MODEL_PATH" \
    --output_dir "$OUT_DIR" \
    --n "$NUM_SAMPLES_CORRECTION" \
    --gpu "$GPUS" \
    --inference_handler "$INFERENCE_HANDLER" \
    --correction_round 2 \
    --previous_run_output_dir "$OUT_DIR" \
    --max_model_len "$MAX_MODEL_LEN" \
    --temp "$TEMPERATURE"
fi

if [[ "${INFERENCE_ONLY:-0}" -eq 0 ]]; then
  _compile_round "_corr2"
fi

# Pass@32（3 轮取平均）
echo "========== Pass@32 (3 rounds average, complete only) =========="
python3 scripts/compute_pass_at_32_v2s_v2c.py "$OUT_DIR" 2>/dev/null || true
python3 scripts/report_pass_at_32.py

echo "Done. Pass@32 (3-round avg): $OUT_DIR/pass_at_32_rounds.txt , 汇总: results/pass_at_32_summary.md"
