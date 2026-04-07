#!/usr/bin/env python3
"""
根据逐条内存 profile 报告（按实际内存占用）确定异常：将「单条 peak_mem_gb > threshold_gb」的证明按题目聚合；
若某题目有 2+ 条超阈值，或开启 --add-single 时单条超阈值，则加入 abnormal_problems 并导出到 abnormal_proofs。
用法:
  python3 scripts/update_abnormal_from_profile.py results/logs/subchunk_memory_report.json \\
    --input_codes results/minif2f/round_2/to_inference_codes.json --bench minif2f --round round_2 --threshold_gb 20
  python3 scripts/update_abnormal_from_profile.py results/logs/v2c_subchunk_profile.json \\
    --input_codes results/minif2f_v2c/to_inference_codes.json --bench minif2f_v2c --round round_0 --threshold_gb 15 --add-single
"""
import argparse
import json
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ABNORMAL_ROOT = os.path.join(ZAM_LEAN, "results", "abnormal_proofs")
ABNORMAL_JSON = os.path.join(ZAM_LEAN, "results", "abnormal_problems.json")


def problem_base(problem_id):
    if not problem_id:
        return ""
    return re.sub(r"_g\d+$", "", str(problem_id))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_json", help="e.g. subchunk5_memory_report.json (has results[].problem_id, peak_mem_gb)")
    ap.add_argument("--input_codes", required=True, help="to_inference_codes.json to export full problem proofs")
    ap.add_argument("--bench", required=True, help="e.g. minif2f")
    ap.add_argument("--round", required=True, help="e.g. round_2")
    ap.add_argument("--threshold_gb", type=int, default=20, help="Single proof peak above this (GB) = problematic")
    ap.add_argument("--add-single", action="store_true", help="Also add problem when only 1 proof exceeds threshold (memory-based single proof)")
    args = ap.parse_args()
    with open(args.profile_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    results = data.get("results") or []
    problematic = [r for r in results if (r.get("peak_mem_gb") or 0) > args.threshold_gb]
    by_base = {}
    for r in problematic:
        base = problem_base(r.get("problem_id") or "")
        if base:
            by_base.setdefault(base, []).append(r["problem_id"])
    if args.add_single:
        bases_to_add = list(by_base.keys())
    else:
        bases_to_add = [b for b, pids in by_base.items() if len(pids) >= 2]
    if not bases_to_add:
        print("No problem above threshold (2+ proofs or --add-single); nothing to add.", file=__import__("sys").stderr)
        return
    with open(ABNORMAL_JSON, "r", encoding="utf-8") as f:
        ab = json.load(f)
    bench_d = ab.setdefault(args.bench, {})
    round_list = bench_d.setdefault(args.round, [])
    for b in bases_to_add:
        if b not in round_list:
            round_list.append(b)
    with open(ABNORMAL_JSON, "w", encoding="utf-8") as f:
        json.dump(ab, f, indent=2, ensure_ascii=False)
    print(f"Added to abnormal_problems: {bases_to_add}", file=__import__("sys").stderr)
    with open(args.input_codes, "r", encoding="utf-8") as f:
        codes = json.load(f)
    for base in bases_to_add:
        subset = [d for d in codes if (d.get("problem_id") or "").startswith(base + "_") or (d.get("problem_id") or "") == base]
        out_dir = os.path.join(ABNORMAL_ROOT, args.bench, args.round, base)
        os.makedirs(out_dir, exist_ok=True)
        for d in subset:
            pid = d.get("problem_id") or d.get("name") or "unknown"
            code = d.get("full_code") or d.get("code") or ""
            if code.strip():
                with open(os.path.join(out_dir, f"{pid}.lean"), "w", encoding="utf-8") as f:
                    f.write(code)
        print(f"Exported {len(subset)} proofs to {out_dir}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
