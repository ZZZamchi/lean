#!/usr/bin/env python3
"""
监控编译进度并估计剩余时间。考虑极端求稳时可单轮串行、关注内存。
用法: python3 scripts/check_compile_status.py [log1 [log2 ...]]
无参时扫描 results/logs/<bench>/compile.log（minif2f、minif2f_v2s、minif2f_v2c、putnambench）。
"""
import os
import re
import sys
import subprocess
from datetime import datetime, timedelta

# 项目根
ZAM_LEAN = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR = os.path.join(ZAM_LEAN, "results", "logs")

def default_logs():
    """无参时：results/logs 下各 bench 的 compile.log，若存在。"""
    logs = []
    if os.path.isdir(LOG_DIR):
        for name in sorted(os.listdir(LOG_DIR)):
            path = os.path.join(LOG_DIR, name, "compile.log")
            if os.path.isfile(path):
                logs.append(path)
    if not logs:
        # 兼容旧用法
        for sub in ("round_2", "round_3"):
            p = os.path.join(ZAM_LEAN, "results", "minif2f", sub, "compile.log")
            if os.path.isfile(p):
                logs.append(p)
    return logs

# 进度行: [2026-02-12 08:00:00] Progress: 100/7808 proofs processed. REPL errors: 0
PROGRESS_RE = re.compile(
    r"\[([^\]]+)\]\s*Progress:\s*(\d+)/(\d+)\s*proofs processed"
)
PROGRESS_RE_NO_TS = re.compile(r"Progress:\s*(\d+)/(\d+)\s*proofs processed")
# 分块合并行: Merged 21504 results -> ...
MERGED_RE = re.compile(r"Merged\s+(\d+)\s+results\s+->")


def parse_log(path: str):
    """返回 (total, [(timestamp_str, done), ...], merged_total)。merged_total 为最后一次 Merged N 的 N。"""
    if not os.path.isfile(path):
        return None, [], None
    total = None
    entries = []
    merged_total = None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            m = MERGED_RE.search(line)
            if m:
                merged_total = int(m.group(1))
            m = PROGRESS_RE.search(line)
            if m:
                ts_str, done_str, total_str = m.groups()
                total = int(total_str)
                entries.append((ts_str, int(done_str)))
                continue
            m = PROGRESS_RE_NO_TS.search(line)
            if m:
                done_str, total_str = m.groups()
                total = int(total_str)
                entries.append((None, int(done_str)))
    return total, entries, merged_total


def estimate_eta(total: int, done: int, entries: list, default_sec_per_proof: float = 20.0):
    """根据最近带时间戳的进度估算剩余时间；否则用 default_sec_per_proof 和 64 workers。"""
    remaining = total - done
    if remaining <= 0:
        return timedelta(0), "done"
    # 取最近两条带时间戳的
    with_ts = [(t, d) for t, d in entries if t is not None]
    num_workers = 64
    if len(with_ts) >= 2:
        try:
            t0 = datetime.strptime(with_ts[-2][0], "%Y-%m-%d %H:%M:%S")
            t1 = datetime.strptime(with_ts[-1][0], "%Y-%m-%d %H:%M:%S")
            delta_done = with_ts[-1][1] - with_ts[-2][1]
            secs = (t1 - t0).total_seconds()
            if secs > 0 and delta_done > 0:
                proofs_per_sec = delta_done / secs
                secs_remaining = remaining / proofs_per_sec
                return timedelta(seconds=int(secs_remaining)), f"from log (~{proofs_per_sec:.1f} proofs/s)"
        except Exception:
            pass
    secs_remaining = (remaining / num_workers) * default_sec_per_proof
    return timedelta(seconds=int(secs_remaining)), f"assumed {default_sec_per_proof}s/proof, {num_workers} workers"


def memory_summary():
    try:
        out = subprocess.run(
            ["free", "-h"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout:
            for line in out.stdout.strip().split("\n"):
                if line.startswith("Mem:"):
                    return line.strip()
    except Exception:
        pass
    return " (free -h failed)"


def main():
    logs = sys.argv[1:] if len(sys.argv) > 1 else default_logs()
    os.chdir(ZAM_LEAN)

    print("=== 内存 ===")
    print(memory_summary())
    print()

    for path in logs:
        name = os.path.basename(os.path.dirname(path))
        total, entries, merged_total = parse_log(path)
        if total is None and merged_total is None:
            print(f"[{name}] 无进度或文件不存在: {path}")
            continue
        if not entries:
            if merged_total is not None:
                print(f"[{name}] 已完成 Merged {merged_total} results")
            else:
                print(f"[{name}] total={total}, 尚无 Progress 行")
            continue
        last_done = entries[-1][1]
        total_show = total or merged_total
        eta, note = estimate_eta(total or 0, last_done, entries)
        pct = 100.0 * last_done / total_show if total_show else 0
        print(f"[{name}] {last_done}/{total_show} ({pct:.1f}%)  ETA: {eta} ({note})")
        if merged_total is not None or (total and last_done >= total):
            print(f"         -> 已完成")
        print()

    print("--- 稳定建议 ---")
    print("极端求稳：同一时间只跑一轮编译，避免多轮并行占满内存。")
    print("当前脚本已按 5GB/worker、70% 可用内存上限做 cap；小内存机会自动减少 workers。")


if __name__ == "__main__":
    main()
