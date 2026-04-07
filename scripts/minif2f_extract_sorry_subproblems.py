#!/usr/bin/env python3
"""
从 minif2f 失败证明构造 sorry 子问题清单（MVP）。

输入:
  - to_inference_codes.json
  - code_compilation_repl.json

输出:
  - subproblem_manifest.json
  - subproblem_dataset.jsonl
"""
import argparse
import json
import os
import re
from typing import Dict, List, Optional, Tuple


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def problem_base(pid: str) -> str:
    if not pid:
        return ""
    return re.sub(r"_g\d+$", "", str(pid))


def first_error(comp_row: Dict) -> Optional[Dict]:
    errs = ((comp_row or {}).get("compilation_result") or {}).get("errors") or []
    if not errs:
        return None
    e = errs[0]
    pos = e.get("pos") or {}
    end = e.get("endPos") or {}
    return {
        "line": pos.get("line"),
        "column": pos.get("column"),
        "end_line": end.get("line"),
        "end_column": end.get("column"),
        "message": e.get("data", ""),
    }


def replace_main_proof_with_sorry(code: str) -> Tuple[str, Optional[Dict]]:
    if not code or not isinstance(code, str):
        return code, None
    marker = ":= by"
    idx = code.rfind(marker)
    if idx < 0:
        return code, None
    replacement_start = idx + len(":=")
    patched = code[:replacement_start] + " by\n  sorry\n"
    span = {
        "proof_start_offset": idx,
        "proof_replaced_from_offset": replacement_start,
        "proof_replaced_to_offset": len(code),
    }
    return patched, span


def main():
    ap = argparse.ArgumentParser(description="Extract sorry subproblems from failed minif2f proofs.")
    ap.add_argument("--input_codes", required=True)
    ap.add_argument("--input_compilation", required=True)
    ap.add_argument("--output_manifest", required=True)
    ap.add_argument("--output_dataset_jsonl", required=True)
    ap.add_argument("--include_passed", action="store_true", help="Also include passed samples.")
    ap.add_argument(
        "--use_not_complete_as_fail",
        action="store_true",
        help="Treat rows with compilation_result.complete==True as OK; extract from incomplete rows "
        "(Putnam / strict Pass@32 口径). Default: use `pass` only.",
    )
    ap.add_argument(
        "--dedupe_problem_base",
        action="store_true",
        help="At most one subproblem per problem_base (first eligible row in codes order).",
    )
    ap.add_argument(
        "--max_subproblems",
        type=int,
        default=None,
        help="Stop after this many manifest entries (after filters).",
    )
    args = ap.parse_args()

    codes = read_json(args.input_codes)
    comp = read_json(args.input_compilation)
    comp_by_id = {str(x.get("problem_id") or x.get("name")): x for x in comp}

    manifest: List[Dict] = []
    dataset_lines: List[str] = []
    seen_bases: set = set()

    for row in codes:
        if args.max_subproblems is not None and len(manifest) >= args.max_subproblems:
            break
        pid = str(row.get("problem_id") or row.get("name") or "")
        if not pid:
            continue
        comp_row = comp_by_id.get(pid)
        if not comp_row:
            continue
        cr = (comp_row.get("compilation_result") or {})
        if args.use_not_complete_as_fail:
            ok = bool(cr.get("complete") or False)
        else:
            ok = bool(cr.get("pass") or False)
        if ok and not args.include_passed:
            continue

        b = problem_base(pid)
        if args.dedupe_problem_base and b in seen_bases:
            continue

        full_code = row.get("full_code") or row.get("code") or ""
        patched_code, span = replace_main_proof_with_sorry(full_code)
        if not span:
            continue

        if args.dedupe_problem_base:
            seen_bases.add(b)

        subproblem_id = f"{pid}__blk_main"
        m = {
            "subproblem_id": subproblem_id,
            "problem_id": pid,
            "problem_base": problem_base(pid),
            "sample_id": pid,
            "block_id": "main_by_block",
            "source_span": span,
            "error_signature": first_error(comp_row),
            "original_code": full_code,
            "patched_code": patched_code,
        }
        manifest.append(m)
        dataset_lines.append(
            json.dumps(
                {
                    "problem_id": subproblem_id,
                    "origin_problem_id": pid,
                    "lean4_code": patched_code,
                },
                ensure_ascii=False,
            )
        )

    out_dir = os.path.dirname(args.output_manifest)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_dir = os.path.dirname(args.output_dataset_jsonl)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(args.output_dataset_jsonl, "w", encoding="utf-8") as f:
        if dataset_lines:
            f.write("\n".join(dataset_lines) + "\n")
        else:
            f.write("")

    print(f"Wrote {len(manifest)} subproblems -> {args.output_manifest}")
    print(f"Wrote {len(dataset_lines)} lines -> {args.output_dataset_jsonl}")


if __name__ == "__main__":
    main()
