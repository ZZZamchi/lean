#!/usr/bin/env python3
"""
离线分析：baseline 下 pass@32 全败的题，在子题侧 DeepSeek/Goedel 的通过情况、错误类型分布、与 router 推荐的一致性。
不跑推理与编译。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def compile_row_subproblem_key(problem_id: str) -> str:
    return re.sub(r"_g\d+$", "", str(problem_id or ""))


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def error_type(sig: Optional[dict]) -> str:
    if not sig:
        return "unknown"
    m = (sig.get("message") or "").lower()
    if "type mismatch" in m:
        return "type_mismatch"
    if "unsolved goals" in m:
        return "unsolved_goals"
    if "rewrite" in m or "rw" in m:
        return "rewrite"
    return "other"


def baseline_pass32_fail_bases(baseline_rows: list) -> Set[str]:
    """Bases where no sample has compilation_result.pass."""
    had_pass: Set[str] = set()
    seen: Set[str] = set()
    for r in baseline_rows:
        pid = r.get("problem_id") or r.get("name")
        if not pid:
            continue
        b = base_id(str(pid))
        seen.add(b)
        if bool((r.get("compilation_result") or {}).get("complete")):
            had_pass.add(b)
    return seen - had_pass


def best_passing_by_subkey(sub_comp: list, pick_shortest: bool) -> Dict[str, dict]:
    by_sub: Dict[str, List[dict]] = {}
    for r in sub_comp:
        pid = r.get("problem_id") or ""
        if not pid:
            continue
        sk = compile_row_subproblem_key(pid)
        if not sk:
            continue
        if not bool((r.get("compilation_result") or {}).get("complete")):
            continue
        by_sub.setdefault(sk, []).append(r)
    out: Dict[str, dict] = {}
    for sk, rows in by_sub.items():
        if pick_shortest:
            out[sk] = min(rows, key=lambda x: len(str(x.get("code") or "")))
        else:
            out[sk] = rows[0]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze pass@32-fail bases vs subproblem compiles (offline).")
    ap.add_argument("--baseline_compile", required=True)
    ap.add_argument("--input_manifest", required=True)
    ap.add_argument("--deepseek_sub_compile", required=True)
    ap.add_argument("--goedel_sub_compile", required=True)
    ap.add_argument("--router_scores", default=None, help="Optional router_scores.json")
    ap.add_argument("--output_md", required=True)
    ap.add_argument("--output_json", default=None)
    args = ap.parse_args()

    baseline = read_json(Path(args.baseline_compile))
    manifest: List[dict] = read_json(Path(args.input_manifest))
    ds_sub = read_json(Path(args.deepseek_sub_compile))
    go_sub = read_json(Path(args.goedel_sub_compile))

    fail_bases = baseline_pass32_fail_bases(baseline)
    ds_best = best_passing_by_subkey(ds_sub, pick_shortest=True)
    go_best = best_passing_by_subkey(go_sub, pick_shortest=True)

    routing: Dict[str, dict] = {}
    if args.router_scores:
        rj = read_json(Path(args.router_scores))
        routing = rj.get("routing") or {}

    # manifest entries whose problem_base is in fail_bases
    subs_on_fail: List[dict] = [m for m in manifest if m.get("problem_base") in fail_bases]

    by_base: Dict[str, List[dict]] = defaultdict(list)
    for m in subs_on_fail:
        pb = m.get("problem_base")
        if pb:
            by_base[str(pb)].append(m)

    per_base_rows = []
    err_hist = Counter()
    pattern = Counter()  # ds_only, go_only, both, neither

    router_cases_single = 0  # exactly one model passes
    router_correct_single = 0  # recommended == winner

    for pb in sorted(fail_bases):
        entries = by_base.get(pb, [])
        n_sub = len(entries)
        n_ds = n_go = n_either = n_both = n_neither = 0
        for m in entries:
            sid = m.get("subproblem_id")
            if not sid:
                continue
            sig = m.get("error_signature") or {}
            err_hist[error_type(sig)] += 1
            ds_ok = sid in ds_best
            go_ok = sid in go_best
            if ds_ok and go_ok:
                pattern["both"] += 1
                n_both += 1
            elif ds_ok:
                pattern["ds_only"] += 1
                n_ds += 1
                rec = (routing.get(sid) or {}).get("recommended_model")
                if rec == "deepseek":
                    router_cases_single += 1
                    router_correct_single += 1
                elif rec == "goedel":
                    router_cases_single += 1
            elif go_ok:
                pattern["go_only"] += 1
                n_go += 1
                rec = (routing.get(sid) or {}).get("recommended_model")
                if rec == "goedel":
                    router_cases_single += 1
                    router_correct_single += 1
                elif rec == "deepseek":
                    router_cases_single += 1
            else:
                pattern["neither"] += 1
                n_neither += 1
            if ds_ok or go_ok:
                n_either += 1
        per_base_rows.append(
            {
                "problem_base": pb,
                "n_subproblems": n_sub,
                "n_ds_only": n_ds,
                "n_go_only": n_go,
                "n_both_pass": n_both,
                "n_neither": n_neither,
                "n_at_least_one_model": n_either,
            }
        )

    bases_with_any_sub_pass = sum(1 for r in per_base_rows if r["n_at_least_one_model"] > 0)
    total_subs = len(subs_on_fail)
    oracle_sub_pass = sum(1 for m in subs_on_fail if (m.get("subproblem_id") or "") in ds_best or (m.get("subproblem_id") or "") in go_best)

    lines = [
        "# pass@32 全败题：子题侧规律分析（离线）",
        "",
        "## 定义与规模",
        "",
        f"- baseline 下 **pass@32 全败** 的 `problem_base` 数量：**{len(fail_bases)}**",
        f"- 这些题在 manifest 中的子题条目数：**{total_subs}**",
        f"- 子题编译 JSON 行数：DeepSeek **{len(ds_sub)}**，Goedel **{len(go_sub)}**",
        "",
        "## 子题级：任一模型是否至少有一条编译通过",
        "",
        f"- 在失败题关联的子题中，**至少被一个模型解出（子题 compile pass）** 的子题数：**{oracle_sub_pass}** / {total_subs}",
        f"- 至少有一个子题被任一模型解出的 **题（base）** 数：**{bases_with_any_sub_pass}** / {len(fail_bases)}",
        "",
        "## 子题模式（每个子题只计一次）",
        "",
        "| 模式 | 计数 | 说明 |",
        "|---|---:|---|",
        f"| 仅 DeepSeek 通过 | {pattern['ds_only']} | |",
        f"| 仅 Goedel 通过 | {pattern['go_only']} | |",
        f"| 双模型均有通过尝试 | {pattern['both']} | 两路各有至少一条 compile pass |",
        f"| 双模型均未通过 | {pattern['neither']} | |",
        "",
        "## 失败题子题的 error_type 分布（与 router 特征一致）",
        "",
    ]
    for k, v in err_hist.most_common():
        lines.append(f"- `{k}`: **{v}**")
    lines.append("")

    if routing:
        lines.append("## Router 推荐 vs 单模型胜出（仅「恰有一边通过」的子题）")
        lines.append("")
        lines.append(f"- 此类子题数：**{router_cases_single}**")
        if router_cases_single:
            acc = router_correct_single / router_cases_single
            lines.append(
                f"- 推荐模型等于通过方：**{router_correct_single}**（准确率 **{acc:.4f}**）"
            )
        lines.append("")

    lines.extend(
        [
            "## 逐题摘要（pass@32 全败的每个 base）",
            "",
            "| problem_base | 子题数 | 仅DS | 仅GO | 双过 | 双挂 | ≥1边通过 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for r in sorted(per_base_rows, key=lambda x: x["problem_base"]):
        lines.append(
            f"| {r['problem_base']} | {r['n_subproblems']} | {r['n_ds_only']} | {r['n_go_only']} | "
            f"{r['n_both_pass']} | {r['n_neither']} | {r['n_at_least_one_model']} |"
        )
    lines.append("")
    lines.append("*说明：混合回填（hybrid）对「仅一边通过」的题最有机会带来端到端增益。*")

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_md}")

    if args.output_json:
        payload = {
            "fail_bases": sorted(fail_bases),
            "n_fail_bases": len(fail_bases),
            "subs_on_fail_bases": total_subs,
            "oracle_subproblems_with_any_model_pass": oracle_sub_pass,
            "bases_with_any_subproblem_pass": bases_with_any_sub_pass,
            "pattern_counts": dict(pattern),
            "error_type_on_fail_subs": dict(err_hist),
            "router_single_winner_cases": router_cases_single,
            "router_matches_single_winner": router_correct_single,
            "per_base": per_base_rows,
        }
        jp = Path(args.output_json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {jp}")


if __name__ == "__main__":
    main()
