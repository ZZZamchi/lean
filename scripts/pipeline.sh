#!/bin/bash
# -----------------------------------------------------------------------------
# Lean 证明生成流水线：支持多种 benchmark，仅推理或推理+编译。
#
# 流程：Inference → Compilation → Summarization（可仅推理或仅编译）
# 多轮：round0 初始 n 条/题，round1/2 对失败样本纠错。
#
# 用法:
#   # 指定 benchmark（自动同步数据集并选数据路径）
#   bash scripts/pipeline.sh --benchmark minif2f [--inference-only]
#   bash scripts/pipeline.sh --benchmark minif2f_v2s [--inference-only]
#   bash scripts/pipeline.sh --benchmark putnambench [--inference-only]
#   bash scripts/pipeline.sh --benchmark minif2f_v2c [--inference-only]  # v2c 数据来自 BENCHMARK_ROOT（默认 ../lean-benchmark，可设 /home/ningmiao/Zam/lean-benchmark）
#   # 或直接指定数据文件
#   bash scripts/pipeline.sh --data-path dataset/minif2f_v2s.jsonl --output-dir results/minif2f_v2s [--inference-only]
#   # 仅编译（需已有 to_inference_codes*.json）
#   bash scripts/pipeline.sh --compile-only --output-dir results/minif2f_v2s
#
# 环境变量：GPUS（默认 2）、CUDA_VISIBLE_DEVICES（指定卡号，如 0,1,2,3）；由调用方按需设置，不自动选卡。
#   MAX_CORRECTION_ROUNDS（默认 2=3 轮）、NUM_SAMPLES_INITIAL=32、VLLM_GPU_MEMORY_UTILIZATION 等。
# -----------------------------------------------------------------------------
set -e
cd "$(dirname "$0")/.."
SCRIPT_DIR="$(dirname "$0")"
ZAM_LEAN="$(pwd)"
# lean-benchmark 路径：默认与 Zam/lean 同级；v2c 数据可在 /home/ningmiao/Zam/lean-benchmark
BENCHMARK_ROOT="${BENCHMARK_ROOT:-$ZAM_LEAN/../lean-benchmark}"

# --- CONFIGURATION ---
MODEL_PATH="${MODEL_PATH:-Goedel-LM/Goedel-Prover-V2-8B}"
DATA_PATH=""
BENCHMARK=""
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_OUTPUT_DIR="results/run_${TIMESTAMP}"

INFERENCE_HANDLER="${INFERENCE_HANDLER:-dpskcot}"
GPUS="${GPUS:-2}"
NUM_SAMPLES_INITIAL="${NUM_SAMPLES_INITIAL:-32}"
NUM_SAMPLES_CORRECTION=2
TEMPERATURE=1.0
MAX_MODEL_LEN=40960
CPUS="${CPUS:-64}"
MAX_CORRECTION_ROUNDS="${MAX_CORRECTION_ROUNDS:-2}"
RUN_INFERENCE_ONLY=0
RUN_COMPILE_ONLY=0

while [[ $# -gt 0 ]] && [[ "$1" == --* ]]; do
  case "$1" in
    --inference-only) RUN_INFERENCE_ONLY=1; shift ;;
    --compile-only)   RUN_COMPILE_ONLY=1; shift ;;
    --output-dir)     BASE_OUTPUT_DIR="$2"; shift 2 ;;
    --data-path)      DATA_PATH="$2"; shift 2 ;;
    --benchmark)      BENCHMARK="$2"; shift 2 ;;
    *) echo "Unknown option $1"; exit 1 ;;
  esac
done

# --- Benchmark → 同步并设置 DATA_PATH ---
if [[ -n "$BENCHMARK" ]]; then
  case "$BENCHMARK" in
    minif2f)
      DATA_PATH="dataset/minif2f.jsonl"
      if [[ ! -f "$DATA_PATH" ]]; then
        python3 scripts/sync_benchmarks.py --bench minif2f --benchmark-root "$BENCHMARK_ROOT" --dataset-dir "$ZAM_LEAN/dataset"
      fi
      ;;
    minif2f_v2s)
      DATA_PATH="dataset/minif2f_v2s.jsonl"
      python3 scripts/sync_benchmarks.py --bench minif2f --minif2f-version v2s --benchmark-root "$BENCHMARK_ROOT" --dataset-dir "$ZAM_LEAN/dataset" 2>/dev/null || true
      if [[ ! -f "$DATA_PATH" ]]; then
        echo "Error: $DATA_PATH not found. Ensure lean-benchmark at $BENCHMARK_ROOT has benchmarks/minif2f/datasets/miniF2F_v2s.jsonl"
        exit 1
      fi
      ;;
    minif2f_v2c)
      DATA_PATH="dataset/minif2f_v2c.jsonl"
      python3 scripts/sync_benchmarks.py --bench minif2f --minif2f-version v2c --benchmark-root "$BENCHMARK_ROOT" --dataset-dir "$ZAM_LEAN/dataset" 2>/dev/null || true
      if [[ ! -f "$DATA_PATH" ]]; then
        echo "Error: $DATA_PATH not found. Ensure lean-benchmark at $BENCHMARK_ROOT has benchmarks/minif2f/datasets/miniF2F_v2c.jsonl (e.g. BENCHMARK_ROOT=/home/ningmiao/Zam/lean-benchmark)"
        exit 1
      fi
      ;;
    putnambench)
      DATA_PATH="dataset/putnambench.jsonl"
      if [[ ! -f "$DATA_PATH" ]]; then
        python3 scripts/sync_benchmarks.py --bench putnambench --benchmark-root "$BENCHMARK_ROOT" --dataset-dir "$ZAM_LEAN/dataset"
      fi
      ;;
    proofnet)
      DATA_PATH="dataset/proofnet.jsonl"
      if [[ ! -f "$DATA_PATH" ]]; then
        python3 scripts/sync_benchmarks.py --bench proofnet --benchmark-root "$BENCHMARK_ROOT" --dataset-dir "$ZAM_LEAN/dataset"
      fi
      if [[ ! -f "$DATA_PATH" ]]; then
        echo "Error: $DATA_PATH not found. Ensure lean-benchmark at $BENCHMARK_ROOT has benchmarks/proofnet/benchmark/test.jsonl"
        exit 1
      fi
      ;;
    *)
      echo "Error: --benchmark must be one of: minif2f, minif2f_v2s, minif2f_v2c, putnambench, proofnet"
      exit 1
      ;;
  esac
fi

# 仅推理且未指定数据路径时，必须指定 --benchmark 或 --data-path
if [[ "$RUN_COMPILE_ONLY" -eq 0 ]] && [[ -z "$DATA_PATH" ]]; then
  echo "Error: For inference, specify --benchmark <minif2f|minif2f_v2s|minif2f_v2c|putnambench|proofnet> or --data-path <path>"
  exit 1
fi

export GPUS="$GPUS"
mkdir -p "$BASE_OUTPUT_DIR"
echo "Output: ${BASE_OUTPUT_DIR} | Data: ${DATA_PATH:-N/A (compile-only)} | GPUs: $GPUS | CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-未设置}"

# --- Main Loop ---
for round in $(seq 0 $MAX_CORRECTION_ROUNDS); do
  SUFFIX=""; [[ $round -gt 0 ]] && SUFFIX="_corr${round}"
  echo
  echo "===================================================="
  echo "===============   Round ${round}   ==============="
  echo "===================================================="

  if [ "$RUN_COMPILE_ONLY" -eq 0 ]; then
    echo "--- [Step 1/3] Inference (Round ${round}) ---"
    if [ "$round" -eq 0 ]; then
      INPUT_ARG="--input_path ${DATA_PATH}"
      PREV_RUN_ARG=""
      NUM_SAMPLES=$NUM_SAMPLES_INITIAL
    else
      INPUT_ARG=""
      PREV_RUN_ARG="--previous_run_output_dir ${BASE_OUTPUT_DIR}"
      NUM_SAMPLES=$NUM_SAMPLES_CORRECTION
    fi
    python3 src/inference.py \
      --model_path "${MODEL_PATH}" \
      --output_dir "${BASE_OUTPUT_DIR}" \
      --n ${NUM_SAMPLES} \
      --gpu ${GPUS} \
      --inference_handler ${INFERENCE_HANDLER} \
      --correction_round ${round} \
      --max_model_len ${MAX_MODEL_LEN} \
      --temp ${TEMPERATURE} \
      ${INPUT_ARG} \
      ${PREV_RUN_ARG}
    SUFFIX=""
    [[ $round -gt 0 ]] && SUFFIX="_corr${round}"
    INFERENCE_OUTPUT_FILE="${BASE_OUTPUT_DIR}/to_inference_codes${SUFFIX}.json"
    if [ ! -f "$INFERENCE_OUTPUT_FILE" ]; then
      echo "Error: Inference output not found: ${INFERENCE_OUTPUT_FILE}"
      exit 1
    fi
    echo "Inference done: ${INFERENCE_OUTPUT_FILE}"
  fi

  if [ "$RUN_INFERENCE_ONLY" -eq 0 ]; then
    echo "--- [Step 2/3] Compilation (Round ${round}) ---"
    INFERENCE_OUTPUT_FILE="${BASE_OUTPUT_DIR}/to_inference_codes${SUFFIX}.json"
    COMPILE_OUTPUT_FILE="${BASE_OUTPUT_DIR}/code_compilation_repl${SUFFIX}.json"
    python3 src/compile.py \
      --input_path "${INFERENCE_OUTPUT_FILE}" \
      --output_path "${COMPILE_OUTPUT_FILE}" \
      --cpu ${CPUS}
    if [ ! -f "$COMPILE_OUTPUT_FILE" ]; then
      echo "Error: Compilation output not found: ${COMPILE_OUTPUT_FILE}"
      exit 1
    fi
    echo "--- [Step 3/3] Summary (Round ${round}) ---"
    FULL_RECORDS_FILE="${BASE_OUTPUT_DIR}/full_records${SUFFIX}.json"
    SUMMARY_OUTPUT_DIR="${BASE_OUTPUT_DIR}/summary_round_${round}"
    mkdir -p "$SUMMARY_OUTPUT_DIR"
    python3 src/summarize.py \
      --input_path "${COMPILE_OUTPUT_FILE}" \
      --full_record_path "${FULL_RECORDS_FILE}" \
      --output_dir "${SUMMARY_OUTPUT_DIR}"
    echo "Summary: ${SUMMARY_OUTPUT_DIR}"
  fi
done

echo
echo "Done. Results in ${BASE_OUTPUT_DIR}"
