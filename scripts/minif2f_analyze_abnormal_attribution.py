#!/usr/bin/env python3
"""
汇总 abnormal_problems.json 中的题，按 id 前缀与关键词打标签，供 prompt / 实验结论使用。
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path


def domain_tag(problem_base: str) -> str:
    s = (problem_base or "").lower()
    if "numbertheory" in s or "mathd_numbertheory" in s:
        return "numbertheory"
    if s.startswith("imo_") or "imosl_" in s:
        return "olympiad"
    if "aime_" in s or "amc" in s:
        return "competition_amc_aime"
    if "algebra_" in s or "mathd_algebra" in s:
        return "algebra"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--abnormal_json",
        default="results/abnormal_problems.json",
        help="Path to abnormal_problems.json",
    )
    ap.add_argument(
        "--output_json",
        default="results/abnormal_attribution_summary.json",
        help="Write aggregated tags and counts",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    path = root / args.abnormal_json
    if not path.is_file():
        print(f"Missing {path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    by_bench: dict = {}
    global_tags: Counter = Counter()

    for bench, rounds in data.items():
        by_bench[bench] = {}
        for round_name, bases in rounds.items():
            tags = [domain_tag(b) for b in bases]
            global_tags.update(tags)
            by_bench[bench][round_name] = {
                "count": len(bases),
                "domain_tag_counts": dict(Counter(tags)),
                "problem_bases": bases,
            }

    out = {
        "source": str(path),
        "by_bench_round": by_bench,
        "global_domain_tag_counts": dict(global_tags),
        "notes": [
            "Heavy memory/OOM abnormal list skews toward olympiad/numbertheory long proofs.",
            "Pair with mine_compilation_failures for tactic-level failure strings.",
        ],
    }
    os.makedirs(os.path.dirname(root / args.output_json), exist_ok=True)
    with open(root / args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {args.output_json}")


if __name__ == "__main__":
    main()
