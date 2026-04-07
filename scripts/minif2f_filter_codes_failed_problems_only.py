#!/usr/bin/env python3
"""
从完整 to_inference_codes 中只保留「baseline 编译结果中该题 pass@32 失败」的样本行。

定义：某题 base_id（去掉 _g\\d+）在 baseline 中若**没有任何一条样本** compilation_result.pass，
则视为失败题，保留该行；否则整题跳过（不写入）。

用于避免对 7808 条全量做 Lean 重编，只重编真正关心的失败题。
"""
import argparse
import json
import os
import re


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def main():
    ap = argparse.ArgumentParser(
        description="Filter inference codes to baseline-failed problems only (pass@32 fail)."
    )
    ap.add_argument("--baseline_compile", required=True, help="code_compilation_repl.json (full)")
    ap.add_argument("--input_codes", required=True, help="to_inference_codes or repaired json list")
    ap.add_argument("--output_codes", required=True)
    args = ap.parse_args()

    baseline = read_json(args.baseline_compile)
    codes = read_json(args.input_codes)

    passed_bases = set()
    for r in baseline:
        if bool((r.get("compilation_result") or {}).get("complete")):
            pid = r.get("problem_id") or r.get("name")
            passed_bases.add(base_id(pid))

    out = []
    skipped = 0
    for row in codes:
        pid = row.get("problem_id") or row.get("name")
        b = base_id(pid)
        if b in passed_bases:
            skipped += 1
            continue
        out.append(row)

    out_dir = os.path.dirname(args.output_codes)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output_codes, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(
        f"Baseline problems with any passing sample: {len(passed_bases)} bases "
        f"(these rows omitted)."
    )
    print(f"Kept {len(out)} rows (failed-problem samples only); skipped {skipped} rows.")
    print(f"Wrote: {args.output_codes}")


if __name__ == "__main__":
    main()
