#!/usr/bin/env python3
"""对比 baseline 与 repaired 再编译：在 full_code 未改行上统计 baseline 通过但第二轮失败的条数。"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="Diagnose pass->fail on unchanged code between two compile runs.")
    ap.add_argument("--baseline_compile", required=True)
    ap.add_argument("--original_codes", required=True)
    ap.add_argument("--repaired_codes", required=True)
    ap.add_argument("--repaired_compile", required=True)
    args = ap.parse_args()

    b = read_json(args.baseline_compile)
    g = read_json(args.repaired_compile)
    orig = read_json(args.original_codes)
    rep = read_json(args.repaired_codes)

    byb = {r.get("problem_id") or r.get("name"): r for r in b}
    byg = {r.get("problem_id") or r.get("name"): r for r in g}
    orig_by = {r.get("problem_id") or r.get("name"): r.get("full_code") for r in orig}
    rep_by = {r.get("problem_id") or r.get("name"): r.get("full_code") for r in rep}

    flip = []
    stable_pass = []
    for pid, rb in byb.items():
        if orig_by.get(pid) != rep_by.get(pid):
            continue
        pb = bool((rb.get("compilation_result") or {}).get("complete"))
        rg = byg.get(pid)
        if not rg:
            continue
        pg = bool((rg.get("compilation_result") or {}).get("complete"))
        if pb and not pg:
            flip.append(pid)
        if pb and pg:
            stable_pass.append(pid)

    def group_pass(rows):
        m = defaultdict(bool)
        for r in rows:
            pid = r.get("problem_id") or r.get("name")
            bid = base_id(pid)
            if bool((r.get("compilation_result") or {}).get("complete")):
                m[bid] = True
        return m

    pb = group_pass(b)
    pg = group_pass(g)
    lost = sum(1 for bid in pb if pb[bid] and not pg.get(bid, False))
    gained = sum(1 for bid in pb if not pb[bid] and pg.get(bid, False))

    print(f"Unchanged rows: baseline pass -> repaired-run fail: {len(flip)}")
    print(f"Unchanged rows: pass both runs: {len(stable_pass)}")
    print(f"pass@32 problems lost: {lost}, gained: {gained}")
    if flip:
        print(f"Sample flip: {flip[:6]}")


if __name__ == "__main__":
    main()
