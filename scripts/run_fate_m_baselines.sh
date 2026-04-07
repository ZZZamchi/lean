#!/usr/bin/env bash
# FATE-M 扩展 baseline：与现有 fate_m_goedel8b / fate_m_32b 对齐的 whole_proof 跑法。
#
# 用法（在仓库根目录）:
#   # DeepSeek-7B，默认 GPU 6,7，全量 150 题，pass@32
#   bash scripts/run_fate_m_baselines.sh deepseek
#
#   # Kimina-7B distill，GPU 4,5
#   GPUS=4,5 bash scripts/run_fate_m_baselines.sh kimina
#
#   # Goedel-8B（若需重跑子集）
#   bash scripts/run_fate_m_baselines.sh goedel8
#
#   # 烟测 12 题
#   LIMIT=12 bash scripts/run_fate_m_baselines.sh deepseek
#
# 断点续跑：再次执行同一 MODEL 命令即可（自动 --resume 到对应 output 目录下的 proof_results.json）。
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL_KEY="${1:-deepseek}"
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"
export CUDA_VISIBLE_DEVICES="${GPUS:-6,7}"

LIMIT_ARGS=()
if [[ -n "${LIMIT:-}" ]]; then
  LIMIT_ARGS=(--limit "$LIMIT")
fi

TP="${TP:-2}"
SAMPLES="${SAMPLES:-32}"
MAX_TOK="${MAX_TOK:-4096}"
MAX_ML="${MAX_ML:-8192}"
# Kimina TP=2 在 GPU 上有其他任务时，0.85 常触发 vLLM「空闲显存不足」；可 export GPU_MEM_UTIL=0.72
GPU_MEM_UTIL="${GPU_MEM_UTIL:-}"

case "$MODEL_KEY" in
  deepseek)
    MODEL_PATH="deepseek-ai/DeepSeek-Prover-V2-7B"
    OUT="results/prover/fate_m_deepseek7b_baseline"
    CHAT=()  # 默认开启 chat template
    ;;
  kimina)
    MODEL_PATH="${KIMINA_MODEL:-AI-MO/Kimina-Prover-Preview-Distill-7B}"
    OUT="results/prover/fate_m_kimina7b_baseline"
    CHAT=()
    GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.72}"
    ;;
  goedel8|goedel8b)
    MODEL_PATH="Goedel-LM/Goedel-Prover-V2-8B"
    OUT="results/prover/fate_m_goedel8b_rerun"
    CHAT=(--no-chat)
    ;;
  *)
    echo "Usage: $0 deepseek|kimina|goedel8"
    exit 1
    ;;
esac

RESUME_ARGS=()
RESUME_FILE="$OUT/proof_results.json"
if [[ -f "$RESUME_FILE" ]]; then
  RESUME_ARGS=(--resume "$RESUME_FILE")
  echo "Resuming from $RESUME_FILE"
fi

mkdir -p "$OUT"
MEM_ARGS=()
if [[ -n "${GPU_MEM_UTIL}" ]]; then
  MEM_ARGS=(--gpu-mem-util "$GPU_MEM_UTIL")
fi
echo "MODEL=$MODEL_PATH OUT=$OUT CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES TP=$TP SAMPLES=$SAMPLES GPU_MEM_UTIL=${GPU_MEM_UTIL:-0.85(default)}"

python3 -m prover.run \
  --dataset fate_m \
  --model "$MODEL_PATH" \
  --output-dir "$OUT" \
  --strategies whole_proof \
  --samples "$SAMPLES" \
  --tp "$TP" \
  --max-tokens "$MAX_TOK" \
  --max-model-len "$MAX_ML" \
  "${MEM_ARGS[@]}" \
  "${CHAT[@]}" \
  "${LIMIT_ARGS[@]}" \
  "${RESUME_ARGS[@]}" \
  2>&1 | tee -a "$OUT/run_console.log"
