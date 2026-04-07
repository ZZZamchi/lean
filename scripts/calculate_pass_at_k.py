#!/usr/bin/env python3
"""计算 Pass@k：从 code_compilation_repl.json 统计每个问题是否有至少一个正确证明。
仅统计 complete=True（无 sorry、无 declaration uses 'sorry'）的证明，含 sorry 的不算。"""
import json
import os
import sys

def pass_at_k(records_path: str, k: int) -> float:
    with open(records_path) as f:
        records = json.load(f)
    if not records:
        return 0.0
    from collections import defaultdict
    by_problem = defaultdict(list)
    for r in records:
        pid = r.get("problem_id") or r.get("name") or ""
        if isinstance(pid, str) and "_g" in pid:
            pid = pid.rsplit("_g", 1)[0]
        cr = r.get("compilation_result") or {}
        passed = cr.get("complete") or False  # 仅完整证明（无 sorry）计为正确
        by_problem[pid].append(passed)
    correct = sum(1 for probs in by_problem.values() if any(probs[:k]))
    return correct / len(by_problem) if by_problem else 0.0

if __name__ == "__main__":
    path = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    p = pass_at_k(path, k)
    print(f"Pass@{k}: {p:.4f}")
    out_path = os.path.join(os.path.dirname(path), "pass_at_32_summary.txt")
    with open(out_path, "w") as f:
        f.write(f"Pass@{k}: {p:.4f}\n")
