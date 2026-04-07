#!/usr/bin/env python3
"""
将子问题通过结果回填到原证明，生成 repaired to_inference_codes.json。

若提供 --baseline_compile（整轮 code_compilation_repl.json），则对已在 baseline 中
编译通过的 problem_id 不再覆盖 full_code，避免把已有正确证明换成子题补丁。
"""
import argparse
import json
import os
import re
from typing import Dict, List


def compile_row_subproblem_key(problem_id: str) -> str:
    """Strip inference attempt suffix `_gN` so compile rows join manifest `subproblem_id`."""
    return re.sub(r"_g\d+$", "", str(problem_id or ""))


def base_id_sample(pid: str) -> str:
    """Strip trailing `_gN` sample suffix (same as minif2f_report_mvp pass@32 grouping)."""
    return re.sub(r"_g\d+$", "", str(pid or ""))


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_complete(row) -> bool:
    """True only when compilation passes WITHOUT sorry."""
    cr = row.get("compilation_result") or {}
    return bool(cr.get("complete"))


def baseline_passing_problem_ids(baseline_rows: list) -> set:
    out = set()
    for r in baseline_rows:
        pid = r.get("problem_id") or r.get("name")
        if not pid:
            continue
        if _is_complete(r):
            out.add(pid)
    return out


def baseline_base_any_pass(baseline_rows: list) -> Dict[str, bool]:
    """base_id -> True if any of 32 samples had complete proof in baseline (for pass@32 guard)."""
    out: Dict[str, bool] = {}
    for r in baseline_rows:
        pid = r.get("problem_id") or r.get("name")
        if not pid:
            continue
        bid = base_id_sample(pid)
        if _is_complete(r):
            out[bid] = True
    return out


def main():
    ap = argparse.ArgumentParser(description="Build repaired codes from passed subproblem attempts.")
    ap.add_argument("--input_manifest", required=True, help="manifest_with_goals.json")
    ap.add_argument("--input_subproblem_compile", required=True, help="compiled subproblem codes json")
    ap.add_argument("--input_original_codes", required=True, help="original to_inference_codes.json")
    ap.add_argument("--output_repaired_codes", required=True)
    ap.add_argument(
        "--baseline_compile",
        default=None,
        help="Round baseline code_compilation_repl.json; rows that already pass are not overwritten.",
    )
    ap.add_argument(
        "--only_if_base_all_fail_baseline",
        action="store_true",
        help="Requires --baseline_compile. Skip backfill for any sample whose base_id already had "
        "≥1 passing sample in baseline (protects pass@32).",
    )
    ap.add_argument(
        "--pick_shortest_passing",
        action="store_true",
        help="Among subproblem compile rows that pass for the same sub_key, pick shortest code.",
    )
    args = ap.parse_args()

    if args.only_if_base_all_fail_baseline and not args.baseline_compile:
        raise SystemExit("--only_if_base_all_fail_baseline requires --baseline_compile")

    manifest = read_json(args.input_manifest)
    sub_comp = read_json(args.input_subproblem_compile)
    orig = read_json(args.input_original_codes)
    baseline_ok = (
        baseline_passing_problem_ids(read_json(args.baseline_compile))
        if args.baseline_compile
        else None
    )
    base_any_pass = (
        baseline_base_any_pass(read_json(args.baseline_compile))
        if args.only_if_base_all_fail_baseline
        else None
    )

    by_sub_passing: Dict[str, List[Dict]] = {}
    for r in sub_comp:
        pid = r.get("problem_id") or ""
        if not pid:
            continue
        sub_key = compile_row_subproblem_key(pid)
        if not sub_key:
            continue
        if not _is_complete(r):
            continue
        by_sub_passing.setdefault(sub_key, []).append(r)

    best_by_sub: Dict[str, Dict] = {}
    for sub_key, rows in by_sub_passing.items():
        if args.pick_shortest_passing:
            best_by_sub[sub_key] = min(rows, key=lambda x: len(str(x.get("code") or "")))
        else:
            best_by_sub[sub_key] = rows[0]

    manifest_by_sub = {m.get("subproblem_id"): m for m in manifest}
    repaired_by_orig = {}
    for sub_id, comp_row in best_by_sub.items():
        m = manifest_by_sub.get(sub_id)
        if not m:
            continue
        orig_pid = m.get("problem_id")
        if not orig_pid:
            continue
        repaired_code = comp_row.get("code")
        if repaired_code:
            repaired_by_orig[orig_pid] = repaired_code

    out = []
    repaired_cnt = 0
    skipped_baseline_pass = 0
    skipped_base_had_pass = 0
    for row in orig:
        pid = row.get("problem_id") or row.get("name")
        new_row = dict(row)
        if pid in repaired_by_orig:
            if base_any_pass is not None and base_any_pass.get(base_id_sample(pid), False):
                skipped_base_had_pass += 1
            elif baseline_ok is not None and pid in baseline_ok:
                skipped_baseline_pass += 1
            else:
                new_row["full_code"] = repaired_by_orig[pid]
                repaired_cnt += 1
        out.append(new_row)

    os.makedirs(os.path.dirname(args.output_repaired_codes) or ".", exist_ok=True)
    with open(args.output_repaired_codes, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Repaired samples: {repaired_cnt}/{len(out)}")
    if baseline_ok is not None:
        print(f"Skipped (baseline already pass): {skipped_baseline_pass}")
    if base_any_pass is not None:
        print(f"Skipped (base had any pass in baseline): {skipped_base_had_pass}")
    print(f"Wrote: {args.output_repaired_codes}")


if __name__ == "__main__":
    main()
