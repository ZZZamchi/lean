#!/usr/bin/env bash
# 预下载 DeepSeek-Prover-V2 与 Kimina-Prover-7B-Distill 到 HuggingFace 缓存（供后续推理使用）
# 说明：HuggingFace 上 DeepSeek-Prover-V2 仅有 7B 和 671B，无 8B，此处下载 7B。
set -e
cd "$(dirname "$0")/.."

echo "Downloading DeepSeek-Prover-V2-7B (HF 上无 8B，仅 7B/671B)..."
huggingface-cli download deepseek-ai/DeepSeek-Prover-V2-7B

echo "Downloading Kimina-Prover-Preview-Distill-7B..."
huggingface-cli download AI-MO/Kimina-Prover-Preview-Distill-7B

echo "Done. 权重已在 HuggingFace 缓存，推理时 MODEL_PATH= 上述 id 即可使用。"
