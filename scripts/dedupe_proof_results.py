#!/usr/bin/env python3
"""
Deduplicate proof_results.json by problem_id.

Keeps one row per problem_id: prefer complete=True, then higher attempts,
then the first seen order (stable).

Use before --resume so the engine does not reload duplicate rows into memory
(506 duplicate rows would otherwise produce an oversized merged JSON).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def pick_better(a: dict, b: dict) -> dict:
    ca, cb = bool(a.get("complete")), bool(b.get("complete"))
    if ca and not cb:
        return a
    if cb and not ca:
        return b
    aa = int(a.get("attempts") or 0)
    ab = int(b.get("attempts") or 0)
    if aa != ab:
        return a if aa >= ab else b
    return a


def dedupe(rows: list[dict]) -> list[dict]:
    by_pid: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        pid = str(r.get("problem_id", ""))
        if not pid:
            continue
        if pid not in by_pid:
            order.append(pid)
            by_pid[pid] = r
        else:
            by_pid[pid] = pick_better(by_pid[pid], r)
    return [by_pid[p] for p in order]


def main():
    ap = argparse.ArgumentParser(description="Dedupe proof_results.json by problem_id")
    ap.add_argument("input", type=Path, help="Input proof_results.json")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Output path (required unless --in-place)")
    ap.add_argument("--in-place", action="store_true", help="Write to input path (with .json.bak backup)")
    args = ap.parse_args()
    if not args.in_place and args.output is None:
        raise SystemExit("Provide -o/--output or use --in-place")
    inp = args.input
    data = json.loads(inp.read_text())
    if not isinstance(data, list):
        raise SystemExit("Expected JSON array")
    out = dedupe(data)
    if args.in_place:
        bak = inp.with_suffix(".json.bak")
        bak.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        inp.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(f"Backed up to {bak}, wrote {len(out)} rows (was {len(data)})")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(f"Wrote {len(out)} rows (was {len(data)}) -> {args.output}")


if __name__ == "__main__":
    main()
