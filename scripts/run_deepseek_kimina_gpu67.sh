#!/usr/bin/env bash
# DeepSeek-Prover-V2 与 Kimina-Prover-7B-Distill：使用 GPU 6,7 跑推理 + 编译（32 worker、chunk 1000、内存监控）
#
# HuggingFace 模型：
#   DeepSeek-Prover-V2-7B: https://huggingface.co/deepseek-ai/DeepSeek-Prover-V2-7B（HF 无 8B）
#   Kimina-Prover-7B-Distill: https://huggingface.co/AI-MO/Kimina-Prover-Preview-Distill-7B
#
# 用法:
#   # DeepSeek-Prover-V2 跑 minif2f_v2s（推理 3 轮 + 编译）
#   MODEL=deepseek BENCH=minif2f_v2s bash scripts/run_deepseek_kimina_gpu67.sh
#
#   # Kimina 跑 minif2f_v2s
#   MODEL=kimina BENCH=minif2f_v2s bash scripts/run_deepseek_kimina_gpu67.sh
#
#   # 仅推理（后续手动跑编译）
#   MODEL=deepseek BENCH=minif2f_v2s INFERENCE_ONLY=1 bash scripts/run_deepseek_kimina_gpu67.sh
#
#   # 仅编译（需已有 to_inference_codes*.json）
#   COMPILE_ONLY=1 COMPILE_BENCH=minif2f_v2s bash scripts/run_deepseek_kimina_gpu67.sh
#
# 环境变量:
#   MODEL=deepseek | kimina  默认 deepseek
#   BENCH=minif2f_v2s | minif2f_v2c | putnambench | proofnet | minif2f
#   INFERENCE_ONLY=1  只跑推理
#   COMPILE_ONLY=1    只跑编译（需 COMPILE_BENCH=）
#   COMPILE_BENCH=    仅编译时指定（与 BENCH 一致即可）
set -e
cd "$(dirname "$0")/.."

# 固定使用 GPU 6,7；PCI_BUS_ID 保证多卡时 cuda:0/1 对应 6,7
export CUDA_VISIBLE_DEVICES=6,7
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export GPUS=2
# 降低显存占用避免 vLLM 报 “Free memory less than desired utilization”（L40 46GB×2）
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.80}"

# 编译：32 worker，chunk 1000，内存监控
export CPU=32
export CHUNK_SIZE=1000

MODEL="${MODEL:-deepseek}"
BENCH="${BENCH:-minif2f_v2s}"
RUN_INFERENCE_ONLY="${INFERENCE_ONLY:-0}"
RUN_COMPILE_ONLY="${COMPILE_ONLY:-0}"

if [[ "$MODEL" = "deepseek" ]]; then
  export MODEL_PATH="${MODEL_PATH:-deepseek-ai/DeepSeek-Prover-V2-7B}"
  export INFERENCE_HANDLER="${INFERENCE_HANDLER:-dpskcot}"
  OUT_DIR="results/deepseek_prover_v2_${BENCH}"
elif [[ "$MODEL" = "kimina" ]]; then
  export MODEL_PATH="${MODEL_PATH:-AI-MO/Kimina-Prover-Preview-Distill-7B}"
  export INFERENCE_HANDLER="${INFERENCE_HANDLER:-kiminacot}"
  OUT_DIR="results/kimina_prover_7b_${BENCH}"
else
  echo "Error: MODEL must be deepseek or kimina"
  exit 1
fi

echo "========== MODEL=$MODEL BENCH=$BENCH OUT_DIR=$OUT_DIR =========="
echo "  MODEL_PATH=$MODEL_PATH INFERENCE_HANDLER=$INFERENCE_HANDLER"
echo "  GPUs=6,7 (CUDA_VISIBLE_DEVICES=6,7) Compile: CPU=$CPU CHUNK_SIZE=$CHUNK_SIZE"

if [[ "$RUN_COMPILE_ONLY" -eq 1 ]]; then
  # 仅编译：需指定 COMPILE_OUT_DIR（含 to_inference_codes.json 的目录）
  export COMPILE_OUT_DIR="${COMPILE_OUT_DIR:?Set COMPILE_OUT_DIR to the dir containing to_inference_codes.json}"
  export COMPILE_BENCH="${COMPILE_BENCH:-$(basename "$COMPILE_OUT_DIR")}"
  echo "Compile-only: COMPILE_OUT_DIR=$COMPILE_OUT_DIR COMPILE_BENCH=$COMPILE_BENCH CPU=$CPU CHUNK_SIZE=$CHUNK_SIZE"
  bash scripts/run_compile_32_with_memory_guard.sh
  exit 0
fi

if [[ "$RUN_COMPILE_ONLY" -eq 0 ]] && [[ "$RUN_INFERENCE_ONLY" -eq 0 ]]; then
  echo "--- Step 1: Inference (GPUs 6,7) ---"
  bash scripts/pipeline.sh --benchmark "$BENCH" --output-dir "$OUT_DIR" --inference-only
  echo "--- Step 2: Compilation (32 workers, chunk 1000, memory guard) ---"
  export COMPILE_OUT_DIR="$OUT_DIR"
  export COMPILE_BENCH="${MODEL}_${BENCH}"
  bash scripts/run_compile_32_with_memory_guard.sh
  echo "Done. Results in $OUT_DIR"
  exit 0
fi

if [[ "$RUN_INFERENCE_ONLY" -eq 1 ]]; then
  echo "--- Inference only (GPUs 6,7) ---"
  bash scripts/pipeline.sh --benchmark "$BENCH" --output-dir "$OUT_DIR" --inference-only
  echo "Inference done. To compile later: COMPILE_ONLY=1 then run compile with input $OUT_DIR/to_inference_codes.json (or use run_compile_32_with_memory_guard with custom path)."
  exit 0
fi
