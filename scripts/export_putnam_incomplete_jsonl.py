#!/usr/bin/env python3
"""Emit a jsonl subset of putnambench for problems not kernel-complete in proof_results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", type=Path, default=Path("dataset/putnambench.jsonl"))
    ap.add_argument("--proof-results", type=Path, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    prev = json.loads(args.proof_results.read_text())
    solved = {r["problem_id"] for r in prev if r.get("complete") and r.get("problem_id")}
    lines_out = []
    for line in args.bench.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        pid = rec.get("problem_id")
        if pid and pid not in solved:
            lines_out.append(line)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines_out) + ("\n" if lines_out else ""))
    print(f"Incomplete problems: {len(lines_out)} -> {args.output}")


if __name__ == "__main__":
    main()
