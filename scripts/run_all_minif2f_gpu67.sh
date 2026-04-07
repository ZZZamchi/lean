#!/usr/bin/env bash
# minif2f + v2 变体（minif2f_v2s, minif2f_v2c）在 GPU 6,7 上依次跑 DeepSeek 与 Kimina：推理 + 编译（32 worker、chunk 1000、内存监控）
# 顺序：minif2f → minif2f_v2s → minif2f_v2c，每个 benchmark 先 DeepSeek 再 Kimina。
# 用法: bash scripts/run_all_minif2f_gpu67.sh
# 仅跑某几个: BENCHES="minif2f minif2f_v2s" bash scripts/run_all_minif2f_gpu67.sh
set -e
cd "$(dirname "$0")/.."

BENCHES="${BENCHES:-minif2f minif2f_v2s minif2f_v2c}"
MODELS="${MODELS:-deepseek kimina}"

for BENCH in $BENCHES; do
  for MODEL in $MODELS; do
    echo ""
    echo "########################################"
    echo "# BENCH=$BENCH MODEL=$MODEL"
    echo "########################################"
    MODEL="$MODEL" BENCH="$BENCH" bash scripts/run_deepseek_kimina_gpu67.sh
  done
done

echo ""
echo "========== 全部完成 =========="
