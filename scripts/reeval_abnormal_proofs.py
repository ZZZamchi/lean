#!/usr/bin/env python3
"""
异常证明复检：从 abnormal_problems 取出题目，用单 worker、每块 1 条、可配置内存上限重新验证。
用法:
  python3 scripts/reeval_abnormal_proofs.py --bench putnambench --round round_0 --mem-gb 300
  python3 scripts/reeval_abnormal_proofs.py --all --mem-gb 300   # 复检所有 bench/round 的异常证明
"""
import argparse
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ABNORMAL_JSON = os.path.join(ZAM_LEAN, "results", "abnormal_problems.json")
COMPILE_BY_CHUNKS = os.path.join(SCRIPT_DIR, "compile_by_chunks.py")


def problem_base(pid):
    if not pid:
        return ""
    return re.sub(r"_g\d+$", "", str(pid).strip())


def _input_codes_path(bench: str, round_name: str) -> str:
    if bench == "minif2f":
        return os.path.join(ZAM_LEAN, "results", "minif2f", round_name, "to_inference_codes.json")
    return os.path.join(ZAM_LEAN, "results", bench, "to_inference_codes.json")


def _out_dir(bench: str, round_name: str) -> str:
    if bench == "minif2f":
        return os.path.join(ZAM_LEAN, "results", "minif2f", round_name)
    return os.path.join(ZAM_LEAN, "results", bench)


def run_reeval(bench: str, round_name: str, mem_gb: int, timeout: int, dry_run: bool) -> int:
    with open(ABNORMAL_JSON, "r", encoding="utf-8") as f:
        abnormal_problems = json.load(f)
    bases = set(abnormal_problems.get(bench, {}).get(round_name, []))
    if not bases:
        return 0

    input_codes_path = _input_codes_path(bench, round_name)
    if not os.path.isfile(input_codes_path):
        print(f"Skip {bench}/{round_name}: {input_codes_path} not found.", file=sys.stderr)
        return 0
    with open(input_codes_path, "r", encoding="utf-8") as f:
        all_codes = json.load(f)
    if not isinstance(all_codes, list):
        print(f"Error: {input_codes_path} must be a list.", file=sys.stderr)
        return 1

    def norm(r):
        code = r.get("full_code") or r.get("code") or ""
        pid = r.get("problem_id") or r.get("name") or ""
        name = r.get("name") or pid
        return {"name": name, "code": code, "problem_id": pid}
    subset = [norm(r) for r in all_codes if problem_base(r.get("problem_id") or r.get("name")) in bases]
    if not subset:
        print(f"No proofs for abnormal bases in {bench}/{round_name}.", file=sys.stderr)
        return 0

    out_dir = _out_dir(bench, round_name)
    os.makedirs(out_dir, exist_ok=True)
    reeval_codes_path = os.path.join(out_dir, "abnormal_reeval_codes.json")
    reeval_results_path = os.path.join(out_dir, "abnormal_reeval_results.json")
    with open(reeval_codes_path, "w", encoding="utf-8") as f:
        json.dump(subset, f, ensure_ascii=False, indent=2)
    print(f"[{bench}/{round_name}] Wrote {len(subset)} proofs ({len(bases)} problems) -> {reeval_codes_path}", file=sys.stderr)

    if dry_run:
        return 0

    env = os.environ.copy()
    env["REPL_MAX_MEM_GB"] = str(mem_gb)
    cmd = [
        sys.executable,
        COMPILE_BY_CHUNKS,
        "--input_path", reeval_codes_path,
        "--output_path", reeval_results_path,
        "--chunk_size", "1",
        "--cpu", "1",
        "--timeout", str(timeout),
        "--keep_chunks",
        "--reeval-abnormal",
    ]
    print(f"[{bench}/{round_name}] Running REPL_MAX_MEM_GB={mem_gb} {' '.join(cmd)}", file=sys.stderr)
    ret = subprocess.run(cmd, cwd=ZAM_LEAN, env=env)
    if ret.returncode != 0:
        print(f"[{bench}/{round_name}] Compile failed (exit {ret.returncode}).", file=sys.stderr)
        return ret.returncode
    print(f"[{bench}/{round_name}] Done -> {reeval_results_path}", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Re-evaluate abnormal proofs: 1 worker, chunk_size=1, configurable memory limit.")
    ap.add_argument("--bench", default=None, help="Benchmark (e.g. putnambench). With --all, ignored.")
    ap.add_argument("--round", default=None, help="Round (e.g. round_0). With --all, ignored.")
    ap.add_argument("--all", action="store_true", help="Run reeval for every bench/round that has abnormal problems")
    ap.add_argument("--mem-gb", type=int, default=300, help="REPL virtual memory limit per proof (GB)")
    ap.add_argument("--timeout", type=int, default=450, help="REPL timeout per proof (seconds)")
    ap.add_argument("--dry-run", action="store_true", help="Only write abnormal_reeval_codes.json, do not compile")
    args = ap.parse_args()

    if not os.path.isfile(ABNORMAL_JSON):
        print(f"Error: {ABNORMAL_JSON} not found.", file=sys.stderr)
        sys.exit(1)
    with open(ABNORMAL_JSON, "r", encoding="utf-8") as f:
        abnormal_problems = json.load(f)

    if args.all:
        tasks = []
        for bench, rounds in abnormal_problems.items():
            for round_name, bases in rounds.items():
                if bases:
                    tasks.append((bench, round_name))
        if not tasks:
            print("No abnormal problems in any bench/round.", file=sys.stderr)
            sys.exit(0)
        for bench, round_name in tasks:
            if run_reeval(bench, round_name, args.mem_gb, args.timeout, args.dry_run) != 0:
                sys.exit(1)
        return 0

    bench = args.bench or "putnambench"
    round_name = args.round or "round_0"
    return run_reeval(bench, round_name, args.mem_gb, args.timeout, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
