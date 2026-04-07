#!/usr/bin/env python3
import argparse
import json
import os
import re


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def _is_complete(row):
    """True only when compilation passes WITHOUT sorry (complete=True)."""
    cr = row.get("compilation_result") or {}
    return bool(cr.get("complete"))


def pass_stats(rows):
    sample_pass = sum(1 for r in rows if _is_complete(r))
    groups = {}
    for r in rows:
        pid = r.get("problem_id") or r.get("name")
        b = base_id(pid)
        groups.setdefault(b, False)
        if _is_complete(r):
            groups[b] = True
    prob_pass = sum(1 for v in groups.values() if v)
    return {
        "samples_total": len(rows),
        "samples_pass": sample_pass,
        "sample_pass_rate": (sample_pass / len(rows) if rows else 0.0),
        "problems_total": len(groups),
        "problems_pass_at_32": prob_pass,
        "pass_at_32": (prob_pass / len(groups) if groups else 0.0),
    }


def main():
    ap = argparse.ArgumentParser(description="Report minif2f MVP gain.")
    ap.add_argument("--baseline_compile", required=True)
    ap.add_argument("--deepseek_repaired_compile", required=True)
    ap.add_argument("--goedel_repaired_compile", required=True)
    ap.add_argument(
        "--hybrid_repaired_compile",
        default=None,
        help="Optional merged compile JSON for DS+GO hybrid backfill.",
    )
    ap.add_argument("--output_md", required=True)
    args = ap.parse_args()

    b = pass_stats(read_json(args.baseline_compile))
    d = pass_stats(read_json(args.deepseek_repaired_compile))
    g = pass_stats(read_json(args.goedel_repaired_compile))
    h = pass_stats(read_json(args.hybrid_repaired_compile)) if args.hybrid_repaired_compile else None

    lines = [
        "# minif2f 子问题修复 MVP 报告",
        "",
        "| 方案 | sample pass rate | pass@32 |",
        "|---|---:|---:|",
        f"| baseline | {b['sample_pass_rate']:.4f} | {b['pass_at_32']:.4f} |",
        f"| repaired (deepseek) | {d['sample_pass_rate']:.4f} | {d['pass_at_32']:.4f} |",
        f"| repaired (goedel) | {g['sample_pass_rate']:.4f} | {g['pass_at_32']:.4f} |",
    ]
    if h is not None:
        lines.append(
            f"| repaired (hybrid) | {h['sample_pass_rate']:.4f} | {h['pass_at_32']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 增益",
            "",
            f"- DeepSeek sample pass rate delta: {d['sample_pass_rate'] - b['sample_pass_rate']:+.4f}",
            f"- DeepSeek pass@32 delta: {d['pass_at_32'] - b['pass_at_32']:+.4f}",
            f"- Goedel sample pass rate delta: {g['sample_pass_rate'] - b['sample_pass_rate']:+.4f}",
            f"- Goedel pass@32 delta: {g['pass_at_32'] - b['pass_at_32']:+.4f}",
        ]
    )
    if h is not None:
        lines.extend(
            [
                f"- Hybrid sample pass rate delta: {h['sample_pass_rate'] - b['sample_pass_rate']:+.4f}",
                f"- Hybrid pass@32 delta: {h['pass_at_32'] - b['pass_at_32']:+.4f}",
            ]
        )
    lines.append("")

    os.makedirs(os.path.dirname(args.output_md), exist_ok=True)
    with open(args.output_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote report: {args.output_md}")


if __name__ == "__main__":
    main()
