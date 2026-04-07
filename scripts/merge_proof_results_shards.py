#!/usr/bin/env python3
"""Merge multiple proof_results.json shards into one (dedupe by problem_id, keep latest).

Usage:
  python3 scripts/merge_proof_results_shards.py \\
    results/prover/minif2f_32b_s0/proof_results.json \\
    results/prover/minif2f_32b_s1/proof_results.json \\
    -o results/prover/minif2f_32b_merged/proof_results.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("shards", nargs="+", type=Path, help="proof_results.json paths")
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    merged: dict[str, dict] = {}
    order: list[str] = []
    for path in args.shards:
        if not path.exists():
            print(f"skip missing: {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data:
            if not isinstance(r, dict) or not r.get("problem_id"):
                continue
            pid = r["problem_id"]
            if pid not in merged:
                order.append(pid)
            merged[pid] = r

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_list = [merged[p] for p in order if p in merged]
    args.output.write_text(json.dumps(out_list, indent=2) + "\n", encoding="utf-8")
    n_complete = sum(1 for r in out_list if r.get("complete"))
    print(f"Merged {len(out_list)} problems, {n_complete} complete -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
