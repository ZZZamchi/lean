# 实验环境（GPU=2, CPUS=64，防 OOM）
# 项目根 = Zam

EXP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$EXP_ROOT"
export ZAM_ROOT="$EXP_ROOT"
export PATH="${HOME}/.elan/bin:${PATH}"

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-6,7}"
export GPUS="${GPUS:-2}"

# 防 OOM：降低 vLLM 显存占比（曾发生内存溢出时使用）
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"

export CPUS="${CPUS:-64}"
# 编译阶段：并发数过大易导致 REPL 卡死，可改为 16/32；单证超时（秒）由 repl_scheduler 读取
# 日志里 "REPL errors: N" = Lean 因超时/EOF 重启次数；若进度卡住且 N 一直涨，可增大 PROOF_TIMEOUT 或减小 COMPILE_CPUS 后重跑
export COMPILE_CPUS="${COMPILE_CPUS:-32}"
export PROOF_TIMEOUT="${PROOF_TIMEOUT:-300}"

export NUM_SAMPLES_INITIAL="${NUM_SAMPLES_INITIAL:-32}"
export INFERENCE_HANDLER="${INFERENCE_HANDLER:-dpskcot}"
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
export OUTPUT_BASE_DIR="$EXP_ROOT/results"
