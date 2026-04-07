#!/usr/bin/env python3
"""
将各 bench 的 abnormal_reeval_results.json 合并回 code_compilation_repl.json（按 problem_id/name 替换），
然后重新运行 report_pass_at_32.py。
用法: python3 scripts/merge_reeval_and_report_pass_at_32.py
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ABNORMAL_JSON = os.path.join(ZAM_LEAN, "results", "abnormal_problems.json")


def _main_result_path(bench: str, round_name: str) -> str:
    if bench == "minif2f":
        return os.path.join(ZAM_LEAN, "results", "minif2f", round_name, "code_compilation_repl.json")
    return os.path.join(ZAM_LEAN, "results", bench, "code_compilation_repl.json")


def _reeval_path(bench: str, round_name: str) -> str:
    if bench == "minif2f":
        return os.path.join(ZAM_LEAN, "results", "minif2f", round_name, "abnormal_reeval_results.json")
    return os.path.join(ZAM_LEAN, "results", bench, "abnormal_reeval_results.json")


def main():
    if not os.path.isfile(ABNORMAL_JSON):
        print("No abnormal_problems.json.", file=sys.stderr)
        return 0
    with open(ABNORMAL_JSON, "r", encoding="utf-8") as f:
        abnormal_problems = json.load(f)

    merged_any = False
    for bench, rounds in abnormal_problems.items():
        for round_name, bases in rounds.items():
            if not bases:
                continue
            main_path = _main_result_path(bench, round_name)
            reeval_path = _reeval_path(bench, round_name)
            if not os.path.isfile(main_path):
                print(f"Skip {bench}/{round_name}: main {main_path} not found.", file=sys.stderr)
                continue
            if not os.path.isfile(reeval_path):
                print(f"Skip {bench}/{round_name}: reeval {reeval_path} not found.", file=sys.stderr)
                continue
            with open(main_path, "r", encoding="utf-8") as f:
                main_list = json.load(f)
            with open(reeval_path, "r", encoding="utf-8") as f:
                reeval_list = json.load(f)
            by_id = {(r.get("problem_id") or r.get("name")): r for r in reeval_list}
            replaced = 0
            for i, rec in enumerate(main_list):
                pid = rec.get("problem_id") or rec.get("name")
                if pid in by_id:
                    main_list[i] = by_id[pid]
                    replaced += 1
            with open(main_path, "w", encoding="utf-8") as f:
                json.dump(main_list, f, ensure_ascii=False, indent=2)
            print(f"[{bench}/{round_name}] Merged {replaced} reeval results -> {main_path}", file=sys.stderr)
            merged_any = True

    if not merged_any:
        print("No reeval results to merge.", file=sys.stderr)
    else:
        # 删除 minif2f 各轮缓存，确保 report 用合并后数据重算
        for r in ("round_2", "round_3"):
            p = os.path.join(ZAM_LEAN, "results", "minif2f", r, "pass_at_32_summary.txt")
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    print(f"Removed {p} for recompute.", file=sys.stderr)
                except Exception:
                    pass
        import subprocess
        report = os.path.join(SCRIPT_DIR, "report_pass_at_32.py")
        print("Running report_pass_at_32.py ...", file=sys.stderr)
        ret = subprocess.run([sys.executable, report], cwd=ZAM_LEAN)
        if ret.returncode != 0:
            sys.exit(ret.returncode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
