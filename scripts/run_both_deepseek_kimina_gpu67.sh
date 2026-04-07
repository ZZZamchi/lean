#!/usr/bin/env bash
# 使用 GPU 6,7 依次跑 DeepSeek-Prover-V2-7B 和 Kimina-Prover-7B-Distill：推理 + 编译（32 worker，chunk 1000，内存监控）
# 先执行 scripts/download_models_gpu67.sh 完成下载后再运行本脚本。
# 用法: BENCH=minif2f_v2s bash scripts/run_both_deepseek_kimina_gpu67.sh
set -e
cd "$(dirname "$0")/.."

BENCH="${BENCH:-minif2f_v2s}"

echo "========== 1/2 DeepSeek-Prover-V2-7B @ $BENCH =========="
MODEL=deepseek BENCH="$BENCH" bash scripts/run_deepseek_kimina_gpu67.sh

echo "========== 2/2 Kimina-Prover-7B-Distill @ $BENCH =========="
MODEL=kimina BENCH="$BENCH" bash scripts/run_deepseek_kimina_gpu67.sh

echo "========== 全部完成 =========="
