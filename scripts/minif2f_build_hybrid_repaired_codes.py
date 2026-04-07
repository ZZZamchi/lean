#!/usr/bin/env python3
"""
对同一子题在 DeepSeek / Goedel 子题编译结果中选一路 proof 回填（仅用已有产物，不推理）。
双模型均通过时：默认按 router_scores 的 recommended_model；无 router 时可选最短 code 或固定偏好。
"""
import argparse
import json
import os
import re
from typing import Dict, List, Optional, Tuple


def compile_row_subproblem_key(problem_id: str) -> str:
    return re.sub(r"_g\d+$", "", str(problem_id or ""))


def base_id_sample(pid: str) -> str:
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
    out: Dict[str, bool] = {}
    for r in baseline_rows:
        pid = r.get("problem_id") or r.get("name")
        if not pid:
            continue
        bid = base_id_sample(pid)
        if _is_complete(r):
            out[bid] = True
    return out


def collect_best_by_sub(sub_comp: list, pick_shortest: bool) -> Dict[str, dict]:
    by_sub: Dict[str, List[dict]] = {}
    for r in sub_comp:
        pid = r.get("problem_id") or ""
        if not pid:
            continue
        sk = compile_row_subproblem_key(pid)
        if not sk:
            continue
        if not _is_complete(r):
            continue
        by_sub.setdefault(sk, []).append(r)
    best: Dict[str, dict] = {}
    for sk, rows in by_sub.items():
        if pick_shortest:
            best[sk] = min(rows, key=lambda x: len(str(x.get("code") or "")))
        else:
            best[sk] = rows[0]
    return best


def choose_hybrid_row(
    sub_id: str,
    ds_row: Optional[dict],
    go_row: Optional[dict],
    routing: Optional[dict],
    pick_shortest_if_both: bool,
    prefer_when_no_router: str,
) -> Tuple[Optional[dict], Optional[str]]:
    ds_ok = ds_row is not None
    go_ok = go_row is not None
    if not ds_ok and not go_ok:
        return None, None
    if ds_ok and not go_ok:
        return ds_row, "deepseek"
    if go_ok and not ds_ok:
        return go_row, "goedel"
    assert ds_row is not None and go_row is not None
    rec = None
    if routing:
        rec = (routing.get(sub_id) or {}).get("recommended_model")
    if rec == "deepseek":
        return ds_row, "deepseek"
    if rec == "goedel":
        return go_row, "goedel"
    if pick_shortest_if_both:
        ld = len(str(ds_row.get("code") or ""))
        lg = len(str(go_row.get("code") or ""))
        if ld <= lg:
            return ds_row, "deepseek"
        return go_row, "goedel"
    if prefer_when_no_router == "deepseek":
        return ds_row, "deepseek"
    return go_row, "goedel"


def main():
    ap = argparse.ArgumentParser(description="Hybrid repaired codes from DS+GO subproblem compiles.")
    ap.add_argument("--input_manifest", required=True)
    ap.add_argument("--deepseek_sub_compile", required=True)
    ap.add_argument("--goedel_sub_compile", required=True)
    ap.add_argument("--input_original_codes", required=True)
    ap.add_argument("--output_repaired_codes", required=True)
    ap.add_argument("--baseline_compile", default=None)
    ap.add_argument(
        "--only_if_base_all_fail_baseline",
        action="store_true",
        help="Skip backfill when base_id had any passing sample in baseline.",
    )
    ap.add_argument(
        "--pick_shortest_passing",
        action="store_true",
        help="When picking within one model, use shortest passing code.",
    )
    ap.add_argument(
        "--router_scores",
        default=None,
        help="router_scores.json: use recommended_model when both models pass.",
    )
    ap.add_argument(
        "--pick_shortest_when_both",
        action="store_true",
        help="When both models pass but router missing/neutral, pick shorter code.",
    )
    ap.add_argument(
        "--prefer_when_no_router",
        choices=("goedel", "deepseek"),
        default="goedel",
        help="When both pass and no router tie-break, prefer this model.",
    )
    args = ap.parse_args()

    if args.only_if_base_all_fail_baseline and not args.baseline_compile:
        raise SystemExit("--only_if_base_all_fail_baseline requires --baseline_compile")

    manifest = read_json(args.input_manifest)
    ds_best = collect_best_by_sub(read_json(args.deepseek_sub_compile), args.pick_shortest_passing)
    go_best = collect_best_by_sub(read_json(args.goedel_sub_compile), args.pick_shortest_passing)
    orig = read_json(args.input_original_codes)

    routing = None
    if args.router_scores:
        rj = read_json(args.router_scores)
        routing = rj.get("routing") or {}

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

    manifest_by_sub = {m.get("subproblem_id"): m for m in manifest}
    repaired_by_orig: Dict[str, str] = {}
    picks = {"deepseek": 0, "goedel": 0}

    for sub_id, m in manifest_by_sub.items():
        if not sub_id:
            continue
        ds_row = ds_best.get(sub_id)
        go_row = go_best.get(sub_id)
        chosen, src = choose_hybrid_row(
            sub_id,
            ds_row,
            go_row,
            routing,
            args.pick_shortest_when_both,
            args.prefer_when_no_router,
        )
        if not chosen or not src:
            continue
        orig_pid = m.get("problem_id")
        if not orig_pid:
            continue
        code = chosen.get("code")
        if not code:
            continue
        repaired_by_orig[orig_pid] = code
        picks[src] += 1

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

    print(f"Hybrid subproblem picks: deepseek={picks['deepseek']}, goedel={picks['goedel']}")
    print(f"Repaired samples: {repaired_cnt}/{len(out)}")
    if baseline_ok is not None:
        print(f"Skipped (baseline already pass): {skipped_baseline_pass}")
    if base_any_pass is not None:
        print(f"Skipped (base had any pass in baseline): {skipped_base_had_pass}")
    print(f"Wrote: {args.output_repaired_codes}")


if __name__ == "__main__":
    main()
