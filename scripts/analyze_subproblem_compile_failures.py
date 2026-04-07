#!/usr/bin/env python3
"""
针对子问题 MVP 目录下 deepseek/goedel 的 code_compilation_repl.json 做失败归因：
- REPL/pexpect EOF vs Lean 类型错误 vs 超时
- 生成代码中 tactic 关键词（simp/aesop/decide 等）计数，辅助判断是否「搜索型」脚本
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

TACTIC_PATTERNS = [
    ("aesop", r"\baesop\b"),
    ("simp", r"\bsimp\b"),
    ("decide", r"\bdecide\b"),
    ("native_decide", r"\bnative_decide\b"),
    ("omega", r"\bomega\b"),
    ("linarith", r"\blinarith\b"),
    ("ring", r"\bring\b"),
    ("norm_num", r"\bnorm_num\b"),
    ("rfl", r"\brfl\b"),
    ("induction", r"\binduction\b"),
]


def classify_failure(cr: dict) -> str:
    parts = []
    if isinstance(cr.get("message"), str) and cr["message"].strip():
        parts.append(cr["message"])
    elif isinstance(cr.get("errors"), list) and cr["errors"]:
        parts.append(str(cr["errors"][0]))
    if cr.get("system_errors"):
        parts.append(str(cr["system_errors"]))
    blob = "\n".join(parts).lower()
    if "pexpect" in blob or "eof error" in blob or "end of file" in blob:
        return "repl_pexpect_eof"
    if "watchdog" in blob or "heartbeat" in blob:
        return "watchdog_or_heartbeat"
    if "timeout" in blob or "timed out" in blob:
        return "timeout"
    if "type mismatch" in blob:
        return "type_mismatch"
    if "unsolved goals" in blob:
        return "unsolved_goals"
    if "unknown identifier" in blob:
        return "unknown_id"
    if not blob.strip():
        return "empty_error"
    return "other_lean"


def tactic_counts(code: str) -> dict[str, int]:
    c = code or ""
    out = {}
    for name, pat in TACTIC_PATTERNS:
        out[name] = len(re.findall(pat, c, flags=re.I))
    return out


def summarize_rows(rows: list) -> dict:
    kinds = Counter()
    tactic_totals: Counter = Counter()
    samples = []
    for r in rows:
        cr = r.get("compilation_result") or {}
        k = classify_failure(cr)
        kinds[k] += 1
        code = r.get("full_code") or r.get("code") or ""
        tc = tactic_counts(code)
        for t, v in tc.items():
            tactic_totals[t] += v
        if len(samples) < 5 and not cr.get("pass"):
            samples.append(
                {
                    "problem_id": r.get("problem_id"),
                    "kind": k,
                    "error_preview": (str(cr.get("system_errors") or cr.get("message") or ""))[:240],
                }
            )
    return {
        "rows": len(rows),
        "fail_kinds": dict(kinds),
        "tactic_keyword_totals_across_rows": dict(tactic_totals),
        "sample_failures": samples,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mvp_dir", default="results/minif2f/round_2/subproblem_mvp")
    ap.add_argument("--output_json", default=None, help="default: <mvp_dir>/subproblem_compile_failure_analysis.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    mvp = root / args.mvp_dir
    out_path = Path(args.output_json) if args.output_json else mvp / "subproblem_compile_failure_analysis.json"

    out = {"mvp_dir": str(mvp), "models": {}}
    for model in ("deepseek", "goedel"):
        p = mvp / model / "code_compilation_repl.json"
        if not p.is_file():
            continue
        rows = json.loads(p.read_text(encoding="utf-8"))
        out["models"][model] = summarize_rows(rows)

    out["notes"] = [
        "若 fail_kinds 以 repl_pexpect_eof 为主：检查 REPL_PEXPECT_MAXREAD、IMPORT_TIMEOUT、工作目录 mathlib4。",
        "tactic_keyword_totals 高而仍失败：多为 Lean 报错而非单纯「搜索过重」；需看具体 message。",
    ]

    os.makedirs(out_path.parent, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
