#!/usr/bin/env python3
"""Summarize self-correction usage from Phase1-16K proof_results.json (field `sc`).

For a proper 0 vs 2 SC ablation, run phase1_official_config on minif2f_ablation_slice10 with
  --self-correction 0 and --self-correction 2 into two output dirs, then compare with compare_phase1_runs.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    path = ROOT / "results" / "experiments" / "phase1_official_16k" / "proof_results.json"
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    if not path.exists():
        print(f"Missing {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    complete = [r for r in data if r.get("complete")]
    with_sc = [r for r in complete if r.get("sc", 0) > 0]
    no_sc = [r for r in complete if r.get("sc", 0) == 0]
    print(f"File: {path}")
    print(f"Total records: {len(data)}")
    print(f"Complete: {len(complete)}")
    print(f"  solved without SC rounds (sc==0): {len(no_sc)}")
    print(f"  solved after SC (sc>0): {len(with_sc)}")
    if with_sc:
        print("  SC-assisted ids:", [r["problem_id"] for r in with_sc])
    if no_sc:
        print("  direct ids:", [r["problem_id"] for r in no_sc])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
