#!/usr/bin/env python3
"""对 v2s/v2c 按轮次分别计算 Pass@32，写入 pass_at_32_rounds.txt。
与 pipeline 命名一致：round0=code_compilation_repl.json, round1=_corr1, round2=_corr2。
若当前仅有 round_0 且题目数为 488（244×2 两轮推理），则按 244 题合并：前 32 条=round_0，后 32 条=round_1，重算 Pass@32。
用法: python3 scripts/compute_pass_at_32_v2s_v2c.py [results/minif2f_v2s] [results/minif2f_v2c]
      不传参则默认两个都算。
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

import calculate_pass_at_k
pass_at_k = calculate_pass_at_k.pass_at_k

K = 32
SUFFIXES = [
    ("", "round_0"),
    ("_corr1", "round_1"),
    ("_corr2", "round_2"),
]

def _split_244_names(bench_dir: str):
    """从 dataset 对应 jsonl 取 split==valid 与 split==test 的 244 题名。
    返回 (valid_set, test_set)，任一不足 244 则对应为 None。"""
    base = os.path.basename(os.path.normpath(bench_dir))
    if base.startswith("results"):
        base = os.path.basename(bench_dir)
    jsonl = os.path.join(ZAM_LEAN, "dataset", base + ".jsonl")
    if not os.path.isfile(jsonl):
        return None, None
    valid_names, test_names = [], []
    with open(jsonl) as f:
        for line in f:
            r = json.loads(line)
            name = r.get("problem_id") or r.get("name") or ""
            if r.get("split") == "valid":
                valid_names.append(name)
            elif r.get("split") == "test":
                test_names.append(name)
    valid_set = set(valid_names) if len(valid_names) == 244 else None
    test_set = set(test_names) if len(test_names) == 244 else None
    return valid_set, test_set

def _load_by_problem(path: str):
    """返回 (base -> list[passed])，按 base 聚合。"""
    with open(path) as f:
        records = json.load(f)
    from collections import defaultdict
    by_problem = defaultdict(list)
    for r in records:
        pid = r.get("problem_id") or r.get("name") or ""
        if isinstance(pid, str) and "_g" in pid:
            pid = pid.rsplit("_g", 1)[0]
        cr = r.get("compilation_result") or {}
        passed = cr.get("complete") or False  # 仅完整证明（无 sorry）计为正确
        by_problem[pid].append(passed)
    return dict(by_problem)

def compute_rounds(bench_dir: str) -> list:
    bench_dir = os.path.abspath(bench_dir)
    path0 = os.path.join(bench_dir, "code_compilation_repl.json")
    results = []
    valid_244, test_244 = _split_244_names(bench_dir)
    if os.path.isfile(path0):
        by_problem = _load_by_problem(path0)
        if valid_244 is not None or test_244 is not None:
            # 统计 valid / test / 488 all 的 Pass@32
            if valid_244 is not None:
                sub = {k: v for k, v in by_problem.items() if k in valid_244}
                if len(sub) == 244 and all(len(v) == K for v in sub.values()):
                    correct = sum(1 for probs in sub.values() if any(probs[:K]))
                    results.append(("round_0 (244 valid)", correct / 244.0))
            if test_244 is not None:
                sub = {k: v for k, v in by_problem.items() if k in test_244}
                if len(sub) == 244 and all(len(v) == K for v in sub.values()):
                    correct = sum(1 for probs in sub.values() if any(probs[:K]))
                    results.append(("round_0 (244 test)", correct / 244.0))
            if valid_244 is not None and test_244 is not None and len(by_problem) == 488 and all(len(v) == K for v in by_problem.values()):
                correct_all = sum(1 for probs in by_problem.values() if any(probs[:K]))
                results.append(("round_0 (488 all)", correct_all / 488.0))
            if results:
                return results
        # 无 valid/test 过滤或条数不对：按原逻辑整表 Pass@32
        p = pass_at_k(path0, K)
        results.append(("round_0", p))
    for suf, name in SUFFIXES:
        if suf == "":
            continue
        path = os.path.join(bench_dir, f"code_compilation_repl{suf}.json")
        if not os.path.isfile(path):
            continue
        p = pass_at_k(path, K)
        results.append((name, p))
    return results

def main():
    if len(sys.argv) > 1:
        dirs = [os.path.join(ZAM_LEAN, d) if not os.path.isabs(d) else d for d in sys.argv[1:]]
    else:
        dirs = [
            os.path.join(ZAM_LEAN, "results", "minif2f_v2s"),
            os.path.join(ZAM_LEAN, "results", "minif2f_v2c"),
        ]
    for bench_dir in dirs:
        if not os.path.isdir(bench_dir):
            print(f"Skip (not dir): {bench_dir}", file=sys.stderr)
            continue
        results = compute_rounds(bench_dir)
        if not results:
            print(f"No code_compilation_repl*.json in {bench_dir}", file=sys.stderr)
            continue
        out_path = os.path.join(bench_dir, "pass_at_32_rounds.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            if results and ("244 valid" in results[0][0] or "244 test" in results[0][0]):
                f.write("# Pass@32: 244 valid, 244 test, 488 all (v2s/v2c)\n")
            for name, p in results:
                f.write(f"{name} Pass@32: {p:.4f}\n")
            names = [n for n, _ in results]
            if len(results) >= 2 and "either_round" not in names and ("244 valid" in str(names) or "244 test" in str(names)):
                # valid + test 两行时写 (valid+test)/2 作为 average
                p_valid = next((p for n, p in results if "244 valid" in n), None)
                p_test = next((p for n, p in results if "244 test" in n), None)
                if p_valid is not None and p_test is not None:
                    f.write(f"average Pass@32 (valid+test): {(p_valid + p_test) / 2:.4f}\n")
            elif len(results) > 1 and "either_round" not in names:
                avg = sum(p for _, p in results) / len(results)
                f.write(f"average Pass@32: {avg:.4f}\n")
        print(f"{os.path.basename(bench_dir)}: {len(results)} rounds -> {out_path}")
        for name, p in results:
            print(f"  {name} Pass@32: {p:.4f}")

if __name__ == "__main__":
    main()
