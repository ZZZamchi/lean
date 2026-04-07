#!/usr/bin/env python3
"""
将「仅失败题重编」得到的 compile 子集，按 problem_id 合并回完整 baseline 编译结果。

未出现在子集中的行（即 baseline 中本已通过 pass@32 的题）保持 baseline 原样，
这样 pass_stats / pass@32 与全量重编等价，但 Lean 只需跑失败子集。
"""
import argparse
import json
import os
from typing import Dict, List


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(
        description="Merge subset re-compile rows into full baseline compile JSON."
    )
    ap.add_argument("--baseline_compile", required=True, help="Full baseline code_compilation_repl.json")
    ap.add_argument("--subset_compile", required=True, help="Compile JSON for failed-problem rows only")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    base_rows: List = read_json(args.baseline_compile)
    sub_rows: List = read_json(args.subset_compile)
    by_id: Dict[str, dict] = {}
    for r in sub_rows:
        pid = r.get("problem_id") or r.get("name")
        if pid:
            by_id[str(pid)] = r

    out = []
    replaced = 0
    for r in base_rows:
        pid = str(r.get("problem_id") or r.get("name") or "")
        if pid in by_id:
            out.append(by_id[pid])
            replaced += 1
        else:
            out.append(r)

    d = os.path.dirname(args.output)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Baseline rows: {len(base_rows)}, subset rows: {len(sub_rows)}")
    print(f"Replaced {replaced} rows from subset; output length {len(out)} (must match baseline).")
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
