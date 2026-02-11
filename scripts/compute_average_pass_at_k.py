#!/usr/bin/env python3
"""计算 round_1(2/5)、round_2、round_3 的 Pass@32，及 round_2 与 round_3 的平均值，写入 average_pass_at_32.txt。"""
import sys
import os

def read_pass_at_32(round_dir: str) -> float:
    path = os.path.join(round_dir, "pass_at_32_summary.txt")
    if not os.path.isdir(round_dir) or not os.path.isfile(path):
        return 0.0
    with open(path) as f:
        for line in f:
            if "Pass@" in line:
                try:
                    return float(line.split(":")[-1].strip())
                except ValueError:
                    pass
    return 0.0

if __name__ == "__main__":
    # 用法: python3 compute_average_pass_at_k.py <out_dir>  例如 results/minif2f
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "results", "minif2f")
    if not os.path.isdir(out_dir):
        print(f"错误: 目录不存在 {out_dir}", file=sys.stderr)
        sys.exit(1)

    r1 = os.path.join(out_dir, "round_1")
    r2 = os.path.join(out_dir, "round_2")
    r3 = os.path.join(out_dir, "round_3")
    p1 = read_pass_at_32(r1)
    p2 = read_pass_at_32(r2)
    p3 = read_pass_at_32(r3)
    avg23 = (p2 + p3) / 2 if (p2 or p3) else 0.0
    out_path = os.path.join(out_dir, "average_pass_at_32.txt")
    with open(out_path, "w") as f:
        f.write(f"round_1 (2/5) Pass@32: {p1:.4f}\n")
        f.write(f"round_2 Pass@32: {p2:.4f}\n")
        f.write(f"round_3 Pass@32: {p3:.4f}\n")
        f.write(f"average(round_2, round_3) Pass@32: {avg23:.4f}\n")
    print(f"Average(round_2, round_3) Pass@32: {avg23:.4f} -> {out_path}")
