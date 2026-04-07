#!/usr/bin/env python3
"""
OOM 自动修复：从 compile 日志解析最后一次「chunk N compile failed (exit -9)」或「chunk N sub X/Y failed」，
将该块内未在异常列表中的、多证明且代码较长的题目加入 abnormal_problems 并导出证明，
删除不完整 out_*.json，便于续跑时自动跳过并继续。
适用于 minif2f round_2/round_3、minif2f_v2s、minif2f_v2c、putnambench、proofnet（与 compile_by_chunks 的 bench/round 一致）。

按实际内存占用确定异常：应使用 scripts/update_abnormal_from_profile.py，传入含 results[].problem_id 与
peak_mem_gb 的 profile 报告（如子块逐条编译时的内存打点）；本脚本仅按代码长度做启发式补充。
用法: python3 scripts/auto_fix_oom_chunk.py [--log results/logs/minif2f_v2c/compile.log] [--chunk-size 2000]
      python3 scripts/auto_fix_oom_chunk.py [--log results/logs/compile_32_sequential.log] [--chunk-size 64]  # minif2f round_2/3
返回: 0 表示已修复并删除了不完整块，可续跑；非 0 表示未检测到需修复的 OOM 或失败。
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ABNORMAL_JSON = os.path.join(ZAM_LEAN, "results", "abnormal_problems.json")
ABNORMAL_ROOT = os.path.join(ZAM_LEAN, "results", "abnormal_proofs")
CHUNK_SIZE_DEFAULT = 64
# 代码长度阈值：同一题目 2+ 条且单条超过此长度则视为疑似异常
MIN_CODE_LEN_THRESHOLD = 15000
# 单条证明超过此长度则整题也加入异常（仅作启发式；应以内存 profile 为准，见 update_abnormal_from_profile.py）
MIN_SINGLE_PROOF_LEN_THRESHOLD = 60000


def problem_base(pid):
    if not pid:
        return ""
    return re.sub(r"_g\d+$", "", str(pid))


def _infer_bench_round_and_chunk_size(lines, last_error_pos):
    """从日志推断 bench、round_name、chunk_size。返回 (bench, round_name, chunk_size)。"""
    chunk_size = None
    bench = None
    round_name = None
    # 先判断是否为 v2s/v2c/putnambench：从最后一次 error 往前找最近的 [minif2f_v2c] / [minif2f_v2s] / [putnambench]
    for i in range(last_error_pos, -1, -1):
        line = lines[i]
        if "[minif2f_v2c]" in line:
            bench = "minif2f_v2c"
            round_name = "round_0"
            m = re.search(r"chunk_size=(\d+)", line)
            if m:
                chunk_size = int(m.group(1))
            break
        if "[minif2f_v2s]" in line:
            bench = "minif2f_v2s"
            round_name = "round_0"
            m = re.search(r"chunk_size=(\d+)", line)
            if m:
                chunk_size = int(m.group(1))
            break
        if "[putnambench]" in line:
            bench = "putnambench"
            round_name = "round_0"
            m = re.search(r"chunk_size=(\d+)", line)
            if m:
                chunk_size = int(m.group(1))
            break
        if "[proofnet]" in line:
            bench = "proofnet"
            round_name = "round_0"
            m = re.search(r"chunk_size=(\d+)", line)
            if m:
                chunk_size = int(m.group(1))
            break
    # 非 v2s/v2c/putnambench/proofnet 则为 minif2f round_2/round_3：最后一次 round_3 开始 在 error 之前则为 round_3
    if bench is None:
        bench = "minif2f"
        last_round3 = -1
        for i in range(last_error_pos + 1):
            if "round_2 done. Starting round_3" in lines[i] or "Starting round_3 by chunks" in lines[i]:
                last_round3 = i
        round_name = "round_3" if last_round3 >= 0 else "round_2"
    # 解析 chunk_size：整段日志中的 "chunk_size=..." 或 "size ~..."
    for i in range(last_error_pos + 1):
        line = lines[i]
        if "chunk_size=" in line:
            m = re.search(r"chunk_size=(\d+)", line)
            if m:
                chunk_size = int(m.group(1))
        if "size ~" in line:
            m = re.search(r"size ~(\d+)", line)
            if m:
                chunk_size = int(m.group(1))
    if chunk_size is None:
        chunk_size = CHUNK_SIZE_DEFAULT
    return bench, round_name, chunk_size


def main():
    ap = argparse.ArgumentParser(description="Auto-fix OOM by adding heavy problems to abnormal and removing incomplete chunk output.")
    ap.add_argument("--log", default=os.path.join(ZAM_LEAN, "results", "logs", "compile_32_sequential.log"), help="Compile log path")
    ap.add_argument("--chunk-size", type=int, default=None, help="Chunk size (default: infer from log)")
    args = ap.parse_args()

    if not os.path.isfile(args.log):
        print(f"Log not found: {args.log}", file=sys.stderr)
        return 2

    with open(args.log, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    last_error_chunk = None
    last_error_pos = -1
    for i, line in enumerate(lines):
        m = re.search(r"Error:\s*chunk\s+(\d+)\s+(?:compile|sub\s+\d+/\d+)\s+failed\s+\(exit\s+-9\)", line)
        if m:
            last_error_chunk = int(m.group(1))
            last_error_pos = i

    if last_error_chunk is None:
        print("No 'chunk N compile failed (exit -9)' or 'chunk N sub X/Y failed (exit -9)' found in log.", file=sys.stderr)
        return 1

    bench, round_name, inferred_chunk_size = _infer_bench_round_and_chunk_size(lines, last_error_pos)
    chunk_size = args.chunk_size if args.chunk_size is not None else inferred_chunk_size
    print(f"Inferred bench={bench} round={round_name} chunk_size={chunk_size} (error chunk {last_error_chunk}).", file=sys.stderr)

    if bench in ("minif2f_v2s", "minif2f_v2c", "putnambench", "proofnet"):
        input_path = os.path.join(ZAM_LEAN, "results", bench, "to_inference_codes.json")
        chunk_dir = os.path.join(ZAM_LEAN, "results", bench, "_chunks_code_compilation_repl")
    else:
        input_path = os.path.join(ZAM_LEAN, "results", "minif2f", round_name, "to_inference_codes.json")
        chunk_dir = os.path.join(ZAM_LEAN, "results", "minif2f", round_name, "_chunks_code_compilation_repl")

    if not os.path.isfile(input_path):
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 2

    with open(input_path, "r", encoding="utf-8") as f:
        codes = json.load(f)
    start = last_error_chunk * chunk_size
    end = min(start + chunk_size, len(codes))
    chunk_codes = codes[start:end]

    with open(ABNORMAL_JSON, "r", encoding="utf-8") as f:
        ab = json.load(f)
    existing = set(ab.get(bench, {}).get(round_name, []))

    from collections import defaultdict
    by_base = defaultdict(list)
    for c in chunk_codes:
        pid = c.get("problem_id") or c.get("name") or ""
        ln = len(c.get("full_code") or c.get("code") or "")
        by_base[problem_base(pid)].append((pid, ln))

    to_add = []
    for base, pids in by_base.items():
        if not base or base in existing:
            continue
        max_len = max(l for _, l in pids)
        if len(pids) >= 2 and max_len >= MIN_CODE_LEN_THRESHOLD:
            to_add.append(base)
        elif len(pids) == 1 and max_len >= MIN_SINGLE_PROOF_LEN_THRESHOLD:
            to_add.append(base)

    if not to_add:
        print(f"Chunk {last_error_chunk} ({bench}/{round_name}): no new problem to add (already in abnormal or short).", file=sys.stderr)
    else:
        if bench not in ab:
            ab[bench] = {}
        if round_name not in ab[bench]:
            ab[bench][round_name] = []
        round_list = ab[bench][round_name]
        for b in to_add:
            if b not in round_list:
                round_list.append(b)
        with open(ABNORMAL_JSON, "w", encoding="utf-8") as f:
            json.dump(ab, f, indent=2, ensure_ascii=False)
        print(f"Added to abnormal ({bench}/{round_name}): {to_add}", file=sys.stderr)
        for base in to_add:
            subset = [d for d in codes if problem_base(d.get("problem_id") or d.get("name")) == base]
            out_dir = os.path.join(ABNORMAL_ROOT, bench, round_name, base)
            os.makedirs(out_dir, exist_ok=True)
            for d in subset:
                pid = d.get("problem_id") or d.get("name") or "unknown"
                code = d.get("full_code") or d.get("code") or ""
                if code.strip():
                    with open(os.path.join(out_dir, f"{pid}.lean"), "w", encoding="utf-8") as f:
                        f.write(code)
            print(f"Exported {len(subset)} proofs -> {out_dir}", file=sys.stderr)

    out_path = os.path.join(chunk_dir, f"out_{last_error_chunk:04d}.json")
    if os.path.isfile(out_path):
        try:
            os.remove(out_path)
            print(f"Removed incomplete {out_path}", file=sys.stderr)
        except Exception as e:
            print(f"Failed to remove {out_path}: {e}", file=sys.stderr)
            return 3

    print("Auto-fix done. Re-run guard (with SUBCHUNK_CHUNK_INDEX if needed) to continue.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
