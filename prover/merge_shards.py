#!/usr/bin/env python3
"""
Merge proof_results.json files from multiple shards.
De-duplicates by problem_id, prioritizing complete=True.

Usage:
  python -m prover.merge_shards \
    results/prover/putnambench_nearmiss_shard0/proof_results.json \
    results/prover/putnambench_nearmiss_shard1/proof_results.json \
    -o results/prover/putnambench_nearmiss_merged/proof_results.json
"""
import argparse
import json
import os


def merge(paths: list[str]) -> list[dict]:
    by_pid: dict[str, dict] = {}
    for path in paths:
        with open(path) as f:
            data = json.load(f)
        for r in data:
            pid = r.get("problem_id", "")
            existing = by_pid.get(pid)
            if existing is None:
                by_pid[pid] = r
            elif r.get("complete") and not existing.get("complete"):
                by_pid[pid] = r
            elif r.get("attempts", 0) > existing.get("attempts", 0):
                by_pid[pid] = r
    return list(by_pid.values())


def main():
    parser = argparse.ArgumentParser(description="Merge sharded proof results")
    parser.add_argument("inputs", nargs="+", help="Input proof_results.json files")
    parser.add_argument("-o", "--output", required=True, help="Output path")
    args = parser.parse_args()

    merged = merge(args.inputs)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    solved = sum(1 for r in merged if r.get("complete"))
    print(f"Merged {len(merged)} records from {len(args.inputs)} shards")
    print(f"  Solved: {solved}/{len(merged)} ({solved/len(merged)*100:.1f}%)")


if __name__ == "__main__":
    main()
