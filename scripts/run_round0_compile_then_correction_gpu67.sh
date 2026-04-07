#!/usr/bin/env bash
# Round 0 编译（带内存监控）→ Round 1 推理 → 编译（带监控）→ Round 2 推理 → 编译（带监控）
# 用于 Round 0 推理已完成、但尚未编译的场景（如 inference-only 后进入 Round 1 报错）。
# 用法: OUT_DIR=results/deepseek_prover_v2_minif2f bash scripts/run_round0_compile_then_correction_gpu67.sh
# 可选: MODEL=deepseek（默认）| kimina，会设置 MODEL_PATH / INFERENCE_HANDLER
set -e
cd "$(dirname "$0")/.."

OUT_DIR="${OUT_DIR:-results/deepseek_prover_v2_minif2f}"
export CUDA_VISIBLE_DEVICES=6,7
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.80}"
export CPU=32
export CHUNK_SIZE=1000
export GPUS=2

MODEL="${MODEL:-deepseek}"
if [[ "$MODEL" = "deepseek" ]]; then
  export MODEL_PATH="${MODEL_PATH:-deepseek-ai/DeepSeek-Prover-V2-7B}"
  export INFERENCE_HANDLER="${INFERENCE_HANDLER:-dpskcot}"
elif [[ "$MODEL" = "kimina" ]]; then
  export MODEL_PATH="${MODEL_PATH:-AI-MO/Kimina-Prover-Preview-Distill-7B}"
  export INFERENCE_HANDLER="${INFERENCE_HANDLER:-kiminacot}"
else
  echo "Error: MODEL must be deepseek or kimina"
  exit 1
fi

COMPILE_BENCH_NAME="${COMPILE_BENCH_NAME:-deepseek_minif2f}"
NUM_SAMPLES_CORRECTION="${NUM_SAMPLES_CORRECTION:-2}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-40960}"
TEMPERATURE="${TEMPERATURE:-1.0}"

if [[ ! -f "${OUT_DIR}/to_inference_codes.json" ]]; then
  echo "Error: ${OUT_DIR}/to_inference_codes.json not found. Run Round 0 inference first."
  exit 1
fi

echo "========== Round 0 compile → Correction rounds (memory guard throughout) =========="
echo "  OUT_DIR=$OUT_DIR MODEL=$MODEL COMPILE_BENCH=$COMPILE_BENCH_NAME"

# --- Step 1: Round 0 编译（仅当尚无 code_compilation_repl.json 时必跑；若已有则会重编一次）---
echo ""
echo "--- [1/5] Round 0 compile (memory guard) ---"
export COMPILE_OUT_DIR="$OUT_DIR"
export COMPILE_BENCH="$COMPILE_BENCH_NAME"
bash scripts/run_compile_32_with_memory_guard.sh

if [[ ! -f "${OUT_DIR}/code_compilation_repl.json" ]]; then
  echo "Error: Round 0 compilation did not produce ${OUT_DIR}/code_compilation_repl.json"
  exit 1
fi

# --- Step 2: Round 1 推理 ---
echo ""
echo "--- [2/5] Round 1 inference ---"
python3 src/inference.py \
  --model_path "${MODEL_PATH}" \
  --output_dir "${OUT_DIR}" \
  --previous_run_output_dir "${OUT_DIR}" \
  --n ${NUM_SAMPLES_CORRECTION} \
  --gpu ${GPUS} \
  --inference_handler "${INFERENCE_HANDLER}" \
  --correction_round 1 \
  --max_model_len ${MAX_MODEL_LEN} \
  --temp ${TEMPERATURE}

if [[ ! -f "${OUT_DIR}/to_inference_codes_corr1.json" ]]; then
  echo "Error: Round 1 inference did not produce to_inference_codes_corr1.json"
  exit 1
fi

# --- Step 3: Round 0 + Round 1 编译（内存监控）---
echo ""
echo "--- [3/5] Round 0+1 compile (memory guard) ---"
export COMPILE_OUT_DIR="$OUT_DIR"
export COMPILE_BENCH="$COMPILE_BENCH_NAME"
bash scripts/run_compile_32_with_memory_guard.sh

if [[ ! -f "${OUT_DIR}/code_compilation_repl_corr1.json" ]]; then
  echo "Error: Round 1 compilation did not produce code_compilation_repl_corr1.json"
  exit 1
fi

# --- Step 4: Round 2 推理 ---
echo ""
echo "--- [4/5] Round 2 inference ---"
python3 src/inference.py \
  --model_path "${MODEL_PATH}" \
  --output_dir "${OUT_DIR}" \
  --previous_run_output_dir "${OUT_DIR}" \
  --n ${NUM_SAMPLES_CORRECTION} \
  --gpu ${GPUS} \
  --inference_handler "${INFERENCE_HANDLER}" \
  --correction_round 2 \
  --max_model_len ${MAX_MODEL_LEN} \
  --temp ${TEMPERATURE}

if [[ ! -f "${OUT_DIR}/to_inference_codes_corr2.json" ]]; then
  echo "Error: Round 2 inference did not produce to_inference_codes_corr2.json"
  exit 1
fi

# --- Step 5: 三轮全部编译（内存监控）---
echo ""
echo "--- [5/5] Round 0+1+2 compile (memory guard) ---"
export COMPILE_OUT_DIR="$OUT_DIR"
export COMPILE_BENCH="$COMPILE_BENCH_NAME"
bash scripts/run_compile_32_with_memory_guard.sh

echo ""
echo "Done. Results in ${OUT_DIR}"
echo "  code_compilation_repl.json, code_compilation_repl_corr1.json, code_compilation_repl_corr2.json"
