#!/usr/bin/env python3
"""
将指定问题的所有证明从 to_inference_codes 导出为 .lean 文件到 results/abnormal_proofs/<bench>/<round>/<problem_base>/。
用法:
  python3 scripts/export_abnormal_proofs.py --input results/minif2f/round_2/to_inference_codes.json \\
    --bench minif2f --round round_2 --problem_base amc12a_2020_p4
"""
import argparse
import json
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ABNORMAL_ROOT = os.path.join(ZAM_LEAN, "results", "abnormal_proofs")


def problem_base(problem_id):
    """amc12a_2020_p4_g0 -> amc12a_2020_p4"""
    if not problem_id:
        return ""
    return re.sub(r"_g\d+$", "", problem_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="to_inference_codes.json")
    ap.add_argument("--bench", required=True, help="e.g. minif2f")
    ap.add_argument("--round", required=True, help="e.g. round_2")
    ap.add_argument("--problem_base", required=True, help="e.g. amc12a_2020_p4")
    args = ap.parse_args()
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    base = args.problem_base
    subset = [
        d for d in data
        if (d.get("problem_id") or "").startswith(base + "_") or (d.get("problem_id") or "") == base
    ]
    out_dir = os.path.join(ABNORMAL_ROOT, args.bench, args.round, base)
    os.makedirs(out_dir, exist_ok=True)
    for d in subset:
        pid = d.get("problem_id") or d.get("name") or "unknown"
        code = d.get("full_code") or d.get("code") or ""
        if not code.strip():
            continue
        lean_path = os.path.join(out_dir, f"{pid}.lean")
        with open(lean_path, "w", encoding="utf-8") as f:
            f.write(code)
    print(f"Exported {len(subset)} proofs to {out_dir}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
