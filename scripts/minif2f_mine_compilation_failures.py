#!/usr/bin/env python3
"""
扫描 results/ 下各 benchmark 的 code_compilation_repl.json（及子目录），
汇总编译失败行的错误信息模式（不限 minif2f）。
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path


def bucket_message(msg: str) -> str:
    m = (msg or "").lower()
    raw = msg or ""
    if not m.strip():
        return "empty_or_missing"
    if "eof" in m and "pexpect" in m:
        return "repl_pexpect_eof"
    if "end of file" in m and "eof" in m:
        return "repl_pexpect_eof"
    if "type mismatch" in m or "typeclass" in m:
        return "type_mismatch"
    if "unsolved goals" in m or "unsolved goal" in m:
        return "unsolved_goals"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "deterministic timeout" in m or "heartbeat" in m:
        return "heartbeat_or_det_timeout"
    if "unknown identifier" in m or "unknown constant" in m:
        return "unknown_id"
    if "function expected" in m or "application type mismatch" in m:
        return "application_error"
    if "abnormal_problem_skipped" in m or "abnormal" in m:
        return "abnormal_or_skipped"
    return "other"


def walk_compile_jsons(results_root: Path) -> list[Path]:
    out = []
    for p in results_root.rglob("code_compilation_repl.json"):
        if p.is_file():
            out.append(p)
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results_root", default="results", type=str)
    ap.add_argument("--output_json", default="results/compilation_failure_mine.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    res = root / args.results_root
    if not res.is_dir():
        print(f"No directory {res}")
        return

    paths = walk_compile_jsons(res)
    per_file = {}
    global_fail_buckets: Counter = Counter()
    global_total_rows = 0
    global_fail_rows = 0

    for jp in paths:
        try:
            with open(jp, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        rel = str(jp.relative_to(root))
        fail_b = Counter()
        n = 0
        nf = 0
        for r in rows:
            n += 1
            cr = r.get("compilation_result") or {}
            ok = bool(cr.get("pass"))
            if ok:
                continue
            nf += 1
            parts = []
            if isinstance(cr.get("message"), str) and cr["message"].strip():
                parts.append(cr["message"])
            elif isinstance(cr.get("errors"), list) and cr["errors"]:
                parts.append(str(cr["errors"][0]))
            if cr.get("system_errors"):
                parts.append(str(cr["system_errors"]))
            msg = "\n".join(parts) if parts else ""
            b = bucket_message(msg)
            fail_b[b] += 1
            global_fail_buckets[b] += 1
        global_total_rows += n
        global_fail_rows += nf
        if nf:
            per_file[rel] = {
                "rows": n,
                "fail_rows": nf,
                "fail_bucket_counts": dict(fail_b),
            }

    out = {
        "results_root": str(res),
        "files_scanned": len(paths),
        "files_with_failures": len(per_file),
        "total_rows": global_total_rows,
        "fail_rows": global_fail_rows,
        "global_fail_bucket_counts": dict(global_fail_buckets),
        "per_file": dict(sorted(per_file.items())),
    }
    os.makedirs(os.path.dirname(root / args.output_json), exist_ok=True)
    with open(root / args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {args.output_json} ({global_fail_rows} fails / {global_total_rows} rows)")


if __name__ == "__main__":
    main()
