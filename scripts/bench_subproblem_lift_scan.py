#!/usr/bin/env python3
"""
跨 benchmark 扫描：按题统计 Pass@k（默认与 calculate_pass_at_k 一致用 complete），
找出「k 条全挂」的题，并估计有多少可用「主定理 := by → sorry」挖子题（与 minif2f_extract_sorry_subproblems 同启发式）。

可选：两个模型的编译结果做「跨模型可补」题数（一模型 k 条全挂、另一模型 k 条内 complete）。

用法:
  python3 scripts/bench_subproblem_lift_scan.py --preset putnambench
  python3 scripts/bench_subproblem_lift_scan.py --codes results/fate_h_deepseek_gpu12/to_inference_codes.json \\
      --compile results/fate_h_deepseek_gpu12/code_compilation_repl.json --label fate_ds
  python3 scripts/bench_subproblem_lift_scan.py --preset fate_deepseek --cross_compile results/fate_h_goedel_gpu67/code_compilation_repl.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def problem_base(pid: str) -> str:
    if not pid:
        return ""
    s = str(pid)
    if "_g" in s:
        return s.rsplit("_g", 1)[0]
    return re.sub(r"_g\d+$", "", s)


def replace_main_proof_with_sorry(code: str) -> Tuple[str, Optional[Dict[str, Any]]]:
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


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def group_by_problem(
    rows: List[dict], k: int, use_complete: bool
) -> Dict[str, List[bool]]:
    by: Dict[str, List[bool]] = defaultdict(list)
    for r in rows:
        pid = r.get("problem_id") or r.get("name") or ""
        b = problem_base(str(pid))
        cr = r.get("compilation_result") or {}
        if use_complete:
            ok = bool(cr.get("complete") or False)
        else:
            ok = bool(cr.get("pass") or False)
        by[b].append(ok)
    for b in list(by.keys()):
        by[b] = by[b][:k]
    return dict(by)


def pass_at_k(by: Dict[str, List[bool]]) -> Tuple[int, int, float]:
    total = len(by)
    passed = sum(1 for v in by.values() if any(v))
    rate = passed / total if total else 0.0
    return passed, total, rate


def fail_all_bases(by: Dict[str, List[bool]]) -> List[str]:
    return sorted(b for b, v in by.items() if v and not any(v))


def codes_by_problem(codes: List[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = defaultdict(list)
    for row in codes:
        pid = row.get("problem_id") or row.get("name") or ""
        b = problem_base(str(pid))
        out[b].append(row)
    return dict(out)


def scan_extractable(
    fail_bases: List[str],
    codes_by_b: Dict[str, List[dict]],
    max_check: Optional[int],
) -> Tuple[int, int, int, List[str]]:
    """对 fail_all 题，按 problem_id 排序取第一条样本，试 sorry 切块。"""
    n_ok = 0
    n_no_marker = 0
    n_missing_rows = 0
    examples: List[str] = []
    for i, b in enumerate(fail_bases):
        if max_check is not None and i >= max_check:
            break
        rows = codes_by_b.get(b) or []
        if not rows:
            n_missing_rows += 1
            continue
        rows = sorted(rows, key=lambda r: str(r.get("problem_id") or r.get("name") or ""))
        fc = rows[0].get("full_code") or rows[0].get("code") or ""
        _, span = replace_main_proof_with_sorry(fc)
        if span:
            n_ok += 1
            if len(examples) < 15:
                examples.append(b)
        else:
            n_no_marker += 1
    return n_ok, n_no_marker, n_missing_rows, examples


def cross_model_lift(
    by_a: Dict[str, List[bool]], by_b: Dict[str, List[bool]], label: str
) -> Dict[str, Any]:
    common = set(by_a) & set(by_b)
    a_fail_b_win = sum(
        1 for b in common if by_a.get(b) and not any(by_a[b]) and any(by_b.get(b, []))
    )
    b_fail_a_win = sum(
        1 for b in common if by_b.get(b) and not any(by_b[b]) and any(by_a.get(b, []))
    )
    return {
        "label": label,
        "common_problems": len(common),
        "a_all_fail_b_any_complete": a_fail_b_win,
        "b_all_fail_a_any_complete": b_fail_a_win,
    }


PRESETS: Dict[str, Tuple[str, str]] = {
    "putnambench": (
        "results/putnambench/to_inference_codes.json",
        "results/putnambench/code_compilation_repl.json",
    ),
    "fate_deepseek": (
        "results/fate_h_deepseek_gpu12/to_inference_codes.json",
        "results/fate_h_deepseek_gpu12/code_compilation_repl.json",
    ),
    "fate_goedel": (
        "results/fate_h_goedel_gpu67/to_inference_codes.json",
        "results/fate_h_goedel_gpu67/code_compilation_repl.json",
    ),
    "minif2f_round_2": (
        "results/minif2f/round_2/to_inference_codes.json",
        "results/minif2f/round_2/code_compilation_repl.json",
    ),
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan fail-all problems and subproblem extractability across benchmarks.")
    ap.add_argument("--preset", choices=list(PRESETS.keys()), default=None)
    ap.add_argument("--codes", default=None)
    ap.add_argument("--compile", default=None)
    ap.add_argument("--label", default=None, help="Tag in output JSON")
    ap.add_argument("--k", type=int, default=32)
    ap.add_argument(
        "--metric",
        choices=("complete", "pass"),
        default="complete",
        help="complete 与 calculate_pass_at_k / 官方 Pass@32 一致；pass 为编译通过（可含 sorry）",
    )
    ap.add_argument(
        "--cross_compile",
        default=None,
        help="第二份 code_compilation_repl.json，与主 compile 做跨模型可补统计（题 id 需一致）",
    )
    ap.add_argument("--out_json", default=None)
    ap.add_argument(
        "--max_extract_check",
        type=int,
        default=None,
        help="最多对多少道 fail-all 题试切块（默认全部）",
    )
    args = ap.parse_args()

    root = Path(os.environ.get("ZAM_LEAN", Path(__file__).resolve().parent.parent))
    os.chdir(root)

    if args.preset:
        codes_rel, comp_rel = PRESETS[args.preset]
        codes_path = root / codes_rel
        comp_path = root / comp_rel
        label = args.label or args.preset
    else:
        if not args.codes or not args.compile:
            raise SystemExit("Provide --preset or both --codes and --compile")
        codes_path = Path(args.codes)
        comp_path = Path(args.compile)
        label = args.label or comp_path.parent.name

    use_complete = args.metric == "complete"
    rows = read_json(comp_path)
    by = group_by_problem(rows, args.k, use_complete)
    passed, total, rate = pass_at_k(by)
    fails = fail_all_bases(by)

    codes = read_json(codes_path)
    by_code = codes_by_problem(codes)
    ext_ok, ext_no_marker, ext_missing, examples = scan_extractable(
        fails, by_code, args.max_extract_check
    )

    out: Dict[str, Any] = {
        "label": label,
        "codes_path": str(codes_path),
        "compile_path": str(comp_path),
        "k": args.k,
        "metric": args.metric,
        "problems_total": total,
        "problems_any_pass_at_k": passed,
        "pass_at_k": round(rate, 6),
        "problems_all_fail_at_k": len(fails),
        "fail_all_extractable_sorry_main": ext_ok,
        "fail_all_has_code_but_no_by_marker": ext_no_marker,
        "fail_all_missing_code_rows": ext_missing,
        "extractable_example_bases": examples,
    }

    if args.cross_compile:
        cross_path = Path(args.cross_compile)
        rows_b = read_json(cross_path)
        by_b = group_by_problem(rows_b, args.k, use_complete)
        out["cross"] = cross_model_lift(by, by_b, str(cross_path))

    out_path = Path(args.out_json) if args.out_json else comp_path.parent / "subproblem_lift_scan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    mname = "complete" if use_complete else "pass"
    print(f"[{label}] Pass@{args.k} ({mname}): {passed}/{total} = {rate:.4f}")
    print(f"[{label}] all-fail-at-{args.k}: {len(fails)} problems")
    print(
        f"[{label}] sorry-main extractable among fail-all: {ext_ok} ok, "
        f"{ext_no_marker} no `:= by` marker, {ext_missing} missing codes rows"
    )
    if args.cross_compile and "cross" in out:
        c = out["cross"]
        print(
            f"[cross] common={c['common_problems']} | "
            f"primary_fail_cross_win={c['a_all_fail_b_any_complete']} | "
            f"cross_fail_primary_win={c['b_all_fail_a_any_complete']}"
        )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
