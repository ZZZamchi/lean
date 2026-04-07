#!/usr/bin/env python3
"""
Smoke test: leaf origin naming + stripping `_gN` matches manifest subproblem_id (no GPU).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def compile_row_subproblem_key(problem_id: str) -> str:
    return re.sub(r"_g\d+$", "", str(problem_id or ""))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    mvp = root / "results/minif2f/round_2/subproblem_mvp"
    man_path = mvp / "subproblem_manifest_goal.json"
    ds_path = mvp / "subproblem_dataset_goal.jsonl"
    if not man_path.is_file() or not ds_path.is_file():
        print("SKIP: manifest or dataset missing", file=sys.stderr)
        return 0

    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    subs = {m.get("subproblem_id") for m in manifest if m.get("subproblem_id")}
    line = ds_path.read_text(encoding="utf-8").splitlines()[0]
    row = json.loads(line)
    leaf = row.get("problem_id")
    if not leaf:
        print("FAIL: no problem_id in first dataset line", file=sys.stderr)
        return 1
    if leaf not in subs:
        print(f"FAIL: dataset problem_id {leaf!r} not in manifest", file=sys.stderr)
        return 1
    for ij in (0, 1, 7):
        pid = f"{leaf}_g{ij}"
        k = compile_row_subproblem_key(pid)
        if k != leaf:
            print(f"FAIL: strip mismatch {pid!r} -> {k!r}", file=sys.stderr)
            return 1
    print("OK: leaf id + _g suffix aligns with manifest subproblem_id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
