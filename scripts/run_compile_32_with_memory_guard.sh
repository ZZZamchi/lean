#!/usr/bin/env bash
# 分块编译 + 内存监控，通过参数支持多数据集（minif2f / minif2f_v2s / minif2f_v2c）。
# 用法: CPU=32 CHUNK_SIZE=256 bash scripts/run_compile_32_with_memory_guard.sh
#       COMPILE_BENCH=putnambench CPU=32 CHUNK_SIZE=2000 bash ...  # Putnam 续跑（保留已有块）
#       PUTNAM_FULL_REBUILD=1 COMPILE_BENCH=putnambench bash ...  # Putnam 全量重编（删旧块）
# 日志按数据集分目录: results/logs/<bench>/compile.log, memory_monitor.log, memory_spike_analysis.log
set -e
cd "$(dirname "$0")/.."

# 多 benchmark 逗号分隔时，依次执行本脚本（参数透传）
COMPILE_BENCH="${COMPILE_BENCH:-}"
if [[ "$COMPILE_BENCH" == *","* ]]; then
  for b in $(echo "$COMPILE_BENCH" | tr ',' ' '); do
    export COMPILE_BENCH="$b"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Running guard for $b ==="
    bash "$0" "$@" || exit $?
  done
  exit 0
fi

export REPL_RECYCLE_AFTER="${REPL_RECYCLE_AFTER:-80}"
export REPL_MAX_MEM_GB="${REPL_MAX_MEM_GB:-30}"
export CHUNK_GAP_SEC="${CHUNK_GAP_SEC:-30}"
export MEM_DROP_BELOW_GB="${MEM_DROP_BELOW_GB:-0}"
export MEM_WAIT_MAX_SEC="${MEM_WAIT_MAX_SEC:-240}"
# putnambench 在安全前提下使用更大块和更多 worker（可被环境变量覆盖）
if [[ "$COMPILE_BENCH" = "putnambench" ]]; then
  CHUNK_SIZE="${CHUNK_SIZE:-256}"
  CPU="${CPU:-32}"
else
  CHUNK_SIZE="${CHUNK_SIZE:-64}"
  CPU="${CPU:-8}"
fi
TIMEOUT="${TIMEOUT:-450}"
CHUNK_INDEX="${CHUNK_INDEX:-}"
DYNAMIC_WORKERS="${DYNAMIC_WORKERS:-0}"
export SUBCHUNK_CHUNK_INDEX="${SUBCHUNK_CHUNK_INDEX:-57,70}"
export SUBCHUNK_SIZE="${SUBCHUNK_SIZE:-8}"
if [ -z "${MEM_THRESHOLD_GB+set}" ]; then
  raw=$((150 + 20 * CPU))
  [ "$raw" -gt 500 ] && MEM_THRESHOLD_GB=500 || MEM_THRESHOLD_GB=$raw
fi
MEM_WARN_GB="${MEM_WARN_GB:-$((MEM_THRESHOLD_GB - 80))}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
SPIKE_DELTA_GB="${SPIKE_DELTA_GB:-40}"

# 日志按数据集分目录：results/logs/<bench>/
LOG_BENCH="${COMPILE_BENCH:-minif2f}"
LOG_DIR="results/logs/${LOG_BENCH}"
LOG_COMPILE="${LOG_COMPILE:-${LOG_DIR}/compile.log}"
LOG_MEMORY="${LOG_MEMORY:-${LOG_DIR}/memory_monitor.log}"
LOG_SPIKE="${LOG_SPIKE:-${LOG_DIR}/memory_spike_analysis.log}"
mkdir -p "$LOG_DIR"
if [[ -n "$COMPILE_BENCH" ]]; then
  touch "$LOG_MEMORY" 2>/dev/null || true
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Memory monitor started for $COMPILE_BENCH (threshold ${MEM_THRESHOLD_GB} GB)." >> "$LOG_MEMORY"
fi

# 启动前清理残留 REPL/编译进程，避免与本次运行叠加导致内存翻倍
cleanup_before_start() {
  local killed=0
  pkill -9 -f "compile_by_chunks.py" 2>/dev/null && killed=1
  pkill -9 -f "src/compile.py" 2>/dev/null && killed=1
  killall -9 repl lean lake 2>/dev/null && killed=1
  if [ "$killed" = "1" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaned up leftover compile/REPL processes before start." | tee -a "$LOG_MEMORY"
    sleep 3
  fi
}
cleanup_before_start

get_used_gb() {
  awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{print int((t-a)/1024/1024)}' /proc/meminfo 2>/dev/null || echo 0
}

# 输出 compile 日志最后几行（用于暴涨时上下文）
get_compile_tail() {
  if [ -f "$LOG_COMPILE" ]; then
    tail -n 3 "$LOG_COMPILE" 2>/dev/null | sed 's/^/  | /'
  else
    echo "  | (no compile log)"
  fi
}

# 参数：当前已用内存 used (GB)。打点到 LOG_MEMORY，若相对 PREV_USED 暴涨则追加分析到 LOG_SPIKE。
log_mem_and_check_spike() {
  local used=$1
  local ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[$ts] MemUsed: ${used} GB (threshold ${MEM_THRESHOLD_GB} GB)" | tee -a "$LOG_MEMORY"
  if [ -n "$used" ] && [ "$used" -ge "$MEM_WARN_GB" ] 2>/dev/null; then
    echo "[$ts] WARNING: memory >= ${MEM_WARN_GB} GB (approaching threshold)" | tee -a "$LOG_MEMORY"
  fi
  if [ -n "$PREV_USED" ] && [ -n "$used" ] && [ "$used" -ge 0 ] 2>/dev/null; then
    local delta=$((used - PREV_USED))
    if [ "$delta" -ge "$SPIKE_DELTA_GB" ] 2>/dev/null; then
      local rate=$((delta * 60 / CHECK_INTERVAL))
      {
        echo "[$ts] MEMORY SPIKE DETECTED"
        echo "  prev_gb=$PREV_USED current_gb=$used delta_gb=$delta in ${CHECK_INTERVAL}s (~${rate} GB/min)"
        echo "  config: CPU=$CPU REPL_RECYCLE_AFTER=$REPL_RECYCLE_AFTER CHUNK_SIZE=$CHUNK_SIZE SUBCHUNK_CHUNK_INDEX=${SUBCHUNK_CHUNK_INDEX:-none} SUBCHUNK_SIZE=${SUBCHUNK_SIZE:-0}"
        echo "  compile log tail:"
        get_compile_tail
        echo "---"
      } >> "$LOG_SPIKE"
      echo "[$ts] MEMORY SPIKE: +${delta} GB in ${CHECK_INTERVAL}s (~${rate} GB/min) -> analysis appended to $LOG_SPIKE" | tee -a "$LOG_MEMORY"
    fi
  fi
}

terminate_all() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] TERMINATING: memory >= ${MEM_THRESHOLD_GB} GB or requested." | tee -a "$LOG_MEMORY"
  kill -9 "$COMPILE_PID" 2>/dev/null || true
  killall -9 repl 2>/dev/null || true
  killall -9 lean 2>/dev/null || true
  killall -9 lake 2>/dev/null || true
  pkill -9 -f "src/compile.py" 2>/dev/null || true
  pkill -9 -f "compile_by_chunks.py" 2>/dev/null || true
  sleep 2
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Terminated. MemUsed: $(get_used_gb) GB" | tee -a "$LOG_MEMORY"
}

# 脚本退出时（正常结束、Ctrl+C、SIGTERM）统一清理，避免残留进程
trap 'terminate_all' EXIT
trap 'terminate_all; exit 130' SIGINT SIGTERM

# 构建 compile_by_chunks 的公共参数
CHUNK_EXTRA=()
[ -n "$CHUNK_INDEX" ] && CHUNK_EXTRA+=(--chunk_index "$CHUNK_INDEX")
[ "$DYNAMIC_WORKERS" = "1" ] && CHUNK_EXTRA+=(--dynamic_workers)

# 编译循环：OOM 时自动修复异常块并重试（仅 minif2f round_2/round_3）
AUTO_FIX_MAX="${AUTO_FIX_MAX:-5}"
attempt=0
while true; do
  attempt=$((attempt + 1))
  (
    if [[ -n "${COMPILE_OUT_DIR:-}" ]]; then
      # 自定义目录：round0 + 可选 _corr1/_corr2（与 pipeline 一致）
      for suffix in "" "_corr1" "_corr2"; do
        IN="${COMPILE_OUT_DIR}/to_inference_codes${suffix}.json"
        OUT="${COMPILE_OUT_DIR}/code_compilation_repl${suffix}.json"
        if [[ -f "$IN" ]]; then
          echo "[$(date '+%Y-%m-%d %H:%M:%S')] [COMPILE_OUT_DIR] Round ${suffix:-0} (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, timeout=${TIMEOUT}s)..."
          python3 scripts/compile_by_chunks.py \
            --input_path "$IN" --output_path "$OUT" \
            --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${CHUNK_EXTRA[@]}"
        fi
      done
    elif [[ "$COMPILE_BENCH" = "minif2f_v2s" ]]; then
      # v2s 分轮编译：round0=无后缀, round1=_corr1, round2=_corr2（与 pipeline 一致）
      for suffix in "" "_corr1" "_corr2"; do
        IN="results/minif2f_v2s/to_inference_codes${suffix}.json"
        OUT="results/minif2f_v2s/code_compilation_repl${suffix}.json"
        if [[ -f "$IN" ]]; then
          echo "[$(date '+%Y-%m-%d %H:%M:%S')] [minif2f_v2s] Round ${suffix:-0} by chunks (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, timeout=${TIMEOUT}s)..."
          python3 scripts/compile_by_chunks.py \
            --input_path "$IN" --output_path "$OUT" \
            --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${CHUNK_EXTRA[@]}"
        fi
      done
    elif [[ "$COMPILE_BENCH" = "minif2f_v2c" ]]; then
      # v2c 分轮编译：同上
      for suffix in "" "_corr1" "_corr2"; do
        IN="results/minif2f_v2c/to_inference_codes${suffix}.json"
        OUT="results/minif2f_v2c/code_compilation_repl${suffix}.json"
        if [[ -f "$IN" ]]; then
          echo "[$(date '+%Y-%m-%d %H:%M:%S')] [minif2f_v2c] Round ${suffix:-0} by chunks (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, timeout=${TIMEOUT}s)..."
          python3 scripts/compile_by_chunks.py \
            --input_path "$IN" --output_path "$OUT" \
            --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${CHUNK_EXTRA[@]}"
        fi
      done
    elif [[ "$COMPILE_BENCH" = "putnambench" ]]; then
      IN="results/putnambench/to_inference_codes.json"
      OUT="results/putnambench/code_compilation_repl.json"
      CHUNK_DIR="results/putnambench/_chunks_code_compilation_repl"
      if [[ -f "$IN" ]]; then
        # 默认续跑：保留已有分块，跳过已有 out_*.json；仅当 PUTNAM_FULL_REBUILD=1 时删除并全量重编
        PUTNAM_EXTRA=()
        if [[ "${PUTNAM_FULL_REBUILD}" = "1" ]]; then
          if [[ -f "$OUT" ]] || [[ -d "$CHUNK_DIR" ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [putnambench] PUTNAM_FULL_REBUILD=1: Removing old results: $OUT and $CHUNK_DIR"
            rm -f "$OUT"
            rm -rf "$CHUNK_DIR"
          fi
          PUTNAM_EXTRA=(--force)
          echo "[$(date '+%Y-%m-%d %H:%M:%S')] [putnambench] Full rebuild (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, timeout=${TIMEOUT}s, abnormal skip enabled)..."
        else
          echo "[$(date '+%Y-%m-%d %H:%M:%S')] [putnambench] Resume (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, timeout=${TIMEOUT}s, skip existing chunks, abnormal skip enabled)..."
        fi
        python3 scripts/compile_by_chunks.py \
          --input_path "$IN" --output_path "$OUT" \
          --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${PUTNAM_EXTRA[@]}" "${CHUNK_EXTRA[@]}"
      else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [putnambench] Skip: $IN not found."
      fi
    elif [[ "$COMPILE_BENCH" = "proofnet" ]]; then
      # proofnet 分轮编译：round0=无后缀, round1=_corr1, round2=_corr2。PROOFNET_ROUND_SUFFIX 指定只编一轮（供 run_proofnet_2367.sh 逐轮调用）
      if [[ -n "${PROOFNET_ROUND_SUFFIX+set}" ]]; then
        suffixes=("$PROOFNET_ROUND_SUFFIX")
      else
        suffixes=("" "_corr1" "_corr2")
      fi
      for suffix in "${suffixes[@]}"; do
        IN="results/proofnet/to_inference_codes${suffix}.json"
        OUT="results/proofnet/code_compilation_repl${suffix}.json"
        if [[ -f "$IN" ]]; then
          echo "[$(date '+%Y-%m-%d %H:%M:%S')] [proofnet] Round ${suffix:-0} by chunks (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, timeout=${TIMEOUT}s)..."
          python3 scripts/compile_by_chunks.py \
            --input_path "$IN" --output_path "$OUT" \
            --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${CHUNK_EXTRA[@]}"
        fi
      done
    else
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting round_2 by chunks (chunk_size=${CHUNK_SIZE}, cpu=${CPU}, dynamic_workers=${DYNAMIC_WORKERS}, chunk_index=${CHUNK_INDEX:-all}, timeout=${TIMEOUT}s)..."
      python3 scripts/compile_by_chunks.py \
        --input_path results/minif2f/round_2/to_inference_codes.json \
        --output_path results/minif2f/round_2/code_compilation_repl.json \
        --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${CHUNK_EXTRA[@]}"

      echo "[$(date '+%Y-%m-%d %H:%M:%S')] round_2 done. Starting round_3 by chunks..."
      python3 scripts/compile_by_chunks.py \
        --input_path results/minif2f/round_3/to_inference_codes.json \
        --output_path results/minif2f/round_3/code_compilation_repl.json \
        --chunk_size "$CHUNK_SIZE" --cpu "$CPU" --timeout "$TIMEOUT" --keep_chunks "${CHUNK_EXTRA[@]}"
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All done."
  ) >> "$LOG_COMPILE" 2>&1 &
  COMPILE_PID=$!
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Compile started PID=$COMPILE_PID (attempt $attempt). Monitoring memory every ${CHECK_INTERVAL}s, threshold=${MEM_THRESHOLD_GB}GB." | tee -a "$LOG_MEMORY"

  PREV_USED=""
  KILLED_BY_GUARD=0
  while kill -0 "$COMPILE_PID" 2>/dev/null; do
    used=$(get_used_gb)
    log_mem_and_check_spike "$used"
    if [ -n "$used" ] && [ "$used" -ge "$MEM_THRESHOLD_GB" ] 2>/dev/null; then
      KILLED_BY_GUARD=1
      terminate_all
      break
    fi
    PREV_USED=$used
    sleep "$CHECK_INTERVAL"
  done

  wait "$COMPILE_PID" 2>/dev/null || true
  EXIT_CODE=$?
  if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Compile finished (exit 0)." | tee -a "$LOG_MEMORY"
    exit 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Compile failed (exit $EXIT_CODE)." | tee -a "$LOG_MEMORY"
  # OOM 或异常退出时尝试自动修复并重试（适用于 minif2f round_2/round_3、minif2f_v2s、minif2f_v2c）
  if [ "$attempt" -lt "$AUTO_FIX_MAX" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running auto_fix_oom_chunk (attempt $attempt/$AUTO_FIX_MAX)..." | tee -a "$LOG_MEMORY"
    if python3 scripts/auto_fix_oom_chunk.py --log "$LOG_COMPILE" --chunk-size "${CHUNK_SIZE:-64}" 2>&1 | tee -a "$LOG_MEMORY"; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-fix done. Retrying compile (set SUBCHUNK_CHUNK_INDEX for OOM chunk if needed)." | tee -a "$LOG_MEMORY"
      continue
    fi
  fi
  exit "$EXIT_CODE"
done
