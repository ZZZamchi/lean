#!/usr/bin/env python3
"""
合并「repaired 再编译」与 baseline：对 full_code 与原版一致的行，沿用 baseline 的 compilation_result，
消除二次全量 Lean 编译带来的随机失败（假阴性）；仅对确有改动的行信任 repaired 编译结果。

输出 JSON 行顺序与 repaired_compile 一致（通常与 to_inference_codes 一致）。
"""
import argparse
import copy
import json
from pathlib import Path


def read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="Debias repaired compile using baseline for unchanged full_code rows.")
    ap.add_argument("--baseline_compile", required=True, help="Round baseline code_compilation_repl.json")
    ap.add_argument("--original_codes", required=True, help="Original to_inference_codes.json")
    ap.add_argument("--repaired_codes", required=True, help="repaired_from_*.json (full_code may differ)")
    ap.add_argument("--repaired_compile", required=True, help="Full recompile of repaired_codes")
    ap.add_argument("--output", required=True, help="Merged compile JSON for reporting")
    args = ap.parse_args()

    baseline_rows = read_json(args.baseline_compile)
    rep_comp = read_json(args.repaired_compile)
    orig = read_json(args.original_codes)
    rep = read_json(args.repaired_codes)

    by_pid_b = {r.get("problem_id") or r.get("name"): r for r in baseline_rows}
    orig_fc = {r.get("problem_id") or r.get("name"): r.get("full_code") for r in orig}
    rep_fc = {r.get("problem_id") or r.get("name"): r.get("full_code") for r in rep}

    out = []
    n_debias = 0
    n_repaired = 0
    missing_b = 0
    for row in rep_comp:
        pid = row.get("problem_id") or row.get("name")
        o = orig_fc.get(pid)
        rfc = rep_fc.get(pid)
        if o is None or rfc is None:
            out.append(row)
            continue
        if o == rfc:
            br = by_pid_b.get(pid)
            if br is None:
                missing_b += 1
                out.append(row)
                continue
            new_row = copy.deepcopy(row)
            new_row["compilation_result"] = copy.deepcopy(br.get("compilation_result") or {})
            if "verify_time" in br:
                new_row["verify_time"] = br.get("verify_time")
            out.append(new_row)
            n_debias += 1
        else:
            out.append(row)
            n_repaired += 1

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Debiased merge: unchanged_rows_use_baseline={n_debias}, "
        f"changed_rows_use_repaired_compile={n_repaired}, missing_baseline_pid={missing_b} -> {args.output}"
    )


if __name__ == "__main__":
    main()
