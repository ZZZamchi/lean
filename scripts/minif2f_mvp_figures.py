#!/usr/bin/env python3
"""
从已有 baseline / merged 编译 JSON 生成 MVP 对比柱状图（无需重跑编译）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def pass_stats(rows: list) -> dict:
    sample_pass = sum(1 for r in rows if bool((r.get("compilation_result") or {}).get("complete")))
    groups: dict[str, bool] = {}
    for r in rows:
        pid = r.get("problem_id") or r.get("name")
        b = base_id(str(pid))
        groups.setdefault(b, False)
        if bool((r.get("compilation_result") or {}).get("complete")):
            groups[b] = True
    prob_pass = sum(1 for v in groups.values() if v)
    n = len(rows)
    g = len(groups)
    return {
        "sample_pass_rate": (sample_pass / n if n else 0.0),
        "pass_at_32": (prob_pass / g if g else 0.0),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--write",
        action="store_true",
        help="Write PNG files. Default: exit without generating images (专注分析时可不传).",
    )
    ap.add_argument("--baseline", default="results/minif2f/round_2/code_compilation_repl.json")
    ap.add_argument("--deepseek_merged", default="results/minif2f/round_2/subproblem_mvp/repaired_from_deepseek_compiled_merged.json")
    ap.add_argument("--goedel_merged", default="results/minif2f/round_2/subproblem_mvp/repaired_from_goedel_compiled_merged.json")
    ap.add_argument("--out_dir", default="results/minif2f/round_2/subproblem_mvp/figures")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    if not args.write:
        print("Skip figure generation (pass --write to save PNGs).")
        return

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skip figure generation")
        return

    def load(p: str) -> list:
        path = root / p
        if not path.is_file():
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    b = pass_stats(load(args.baseline))
    d = pass_stats(load(args.deepseek_merged))
    g = pass_stats(load(args.goedel_merged))

    labels = ["baseline", "repaired (DS)", "repaired (Goedel)"]
    p32 = [b["pass_at_32"], d["pass_at_32"], g["pass_at_32"]]
    spr = [b["sample_pass_rate"], d["sample_pass_rate"], g["sample_pass_rate"]]

    out_dir = root / args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x, p32, color=["#334155", "#0ea5e9", "#8b5cf6"])
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("pass@32")
    ax.set_ylim(0, 1.05)
    ax.set_title("minif2f subproblem MVP — pass@32 (merged repaired)")
    fig.tight_layout()
    p32_path = out_dir / "mvp_pass32_bar.png"
    fig.savefig(p32_path, dpi=150)
    plt.close(fig)

    fig2, ax2 = plt.subplots(figsize=(7, 4))
    ax2.bar(x, spr, color=["#334155", "#0ea5e9", "#8b5cf6"])
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels, rotation=15, ha="right")
    ax2.set_ylabel("sample pass rate")
    ax2.set_ylim(0, 1.05)
    ax2.set_title("minif2f subproblem MVP — sample pass rate")
    fig2.tight_layout()
    spr_path = out_dir / "mvp_sample_pass_bar.png"
    fig2.savefig(spr_path, dpi=150)
    plt.close(fig2)

    print(f"Wrote {p32_path} and {spr_path}")


if __name__ == "__main__":
    main()
