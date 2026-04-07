"""批量编译第一轮/第二轮推理结果：读 to_inference_codes.json，经 REPL 验证后写 code_compilation_repl.json。"""
import argparse
import json
import os
import random
import re
import sys

import pandas as pd
from multiprocessing import Manager

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from lean_compiler.repl_scheduler import scheduler


def handle(text):
    """
    清理 Lean 代码：移除 import、set_option、open、maxHeartbeats 0；
    修复模型常见输出错误（与 goedel_EXPERIMENT 一致）：
    - 重复的 ":= by" -> 改为 "by"
    - 缺失的 ":= by"（如 ": type \\n  by"）-> 改为 ": type := \\n  by"
    """
    import re
    if not text or not isinstance(text, str):
        return ""
    lines = text.split("\n")
    filtered = []
    for line in lines:
        s = line.strip()
        if s.startswith(("import", "set_option", "open")):
            continue
        if "maxHeartbeats" in s and "0" in s:
            continue
        filtered.append(line)
    code = "\n".join(filtered).strip()
    # 修复重复 ":= by"
    if ":\n\n:= by" in code:
        code = code.replace(":\n\n:= by", "\n  by")
    if ":=\n\n:= by" in code:
        code = code.replace(":=\n\n:= by", "\n  by")
    # 修复缺失 ":= by"：定理声明后直接 "  by" 应为 " := \\n  by"
    lines = code.split("\n")
    result = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("by") and not stripped.startswith(":="):
            prev_stripped = ""
            for j in range(i - 1, -1, -1):
                if lines[j].strip():
                    prev_stripped = lines[j].rstrip()
                    break
            if prev_stripped and not prev_stripped.endswith(":="):
                line = re.sub(r"^(\s*)by\b", r"\1:= by", line, count=1)
        result.append(line)
    code = "\n".join(result)
    return code


def _available_memory_gb():
    """可用内存（GB），用于限制 worker 数避免 OOM。Linux 读 /proc/meminfo。"""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except Exception:
        pass
    return None


def _problem_base(problem_id):
    """e.g. amc12a_2020_p4_g0 -> amc12a_2020_p4"""
    if not problem_id:
        return ""
    return re.sub(r"_g\d+$", "", str(problem_id))


def _infer_bench_round(input_path):
    """从 input_path 推断 benchmark 与 round，用于异常证明目录。"""
    p = os.path.normpath(input_path)
    for bench in ("minif2f", "putnambench"):
        for round_name in ("round_1", "round_2", "round_3"):
            if bench in p and round_name in p:
                return bench, round_name
    return None, None


def _cap_workers_by_memory(requested: int, max_workers: int = 64, mem_per_worker_gb: float = 5.0, frac: float = 0.7) -> int:
    """根据可用内存限制 worker 数，不超过 max_workers。极端求稳：约 5GB/worker，仅用可用内存 70%。"""
    cap = min(requested, max_workers)
    avail_gb = _available_memory_gb()
    if avail_gb is not None and mem_per_worker_gb > 0:
        by_mem = max(1, int(avail_gb * frac / mem_per_worker_gb))
        cap = min(cap, by_mem)
        if by_mem < requested:
            print(f"Info: capping workers to {cap} by memory (avail ~{avail_gb:.0f}GB, ~{mem_per_worker_gb}GB/worker)", file=sys.stderr)
    return cap


parser = argparse.ArgumentParser(description="Compile Lean proofs via REPL.")
parser.add_argument("--input_path", required=True, type=str, help="to_inference_codes.json")
parser.add_argument("--output_path", required=True, type=str, help="code_compilation_repl.json")
parser.add_argument("--bench", default=None, type=str, help="Benchmark name (minif2f/putnambench); if set with --round, used for abnormal skip instead of inferring from path")
parser.add_argument("--round", default=None, type=str, help="Round name (round_1/round_2/round_3); if set with --bench, used for abnormal skip")
parser.add_argument("--cpu", default=64, type=int, help="Max REPL workers (capped by memory and 64)")
parser.add_argument("--timeout", default=300, type=int, help="REPL timeout per proof (seconds)")
parser.add_argument("--no-mem-cap", action="store_true", help="Disable memory-based worker cap")
parser.add_argument("--no-skip-abnormal", action="store_true", help="Do not skip abnormal problems (for re-eval of abnormal proofs)")
args = parser.parse_args()

num_workers = min(64, max(1, args.cpu))
if not args.no_mem_cap:
    num_workers = _cap_workers_by_memory(num_workers, max_workers=64)
print(f"Using {num_workers} REPL workers (requested --cpu {args.cpu}).", file=sys.stderr)

if not os.path.isfile(args.input_path):
    print(f"Error: input file not found: {args.input_path}", file=sys.stderr)
    sys.exit(1)

with open(args.input_path, "r", encoding="utf-8") as f:
    codes = json.load(f)


code_df = pd.DataFrame(codes)
sub_df = code_df.copy()
if "problem_id" not in sub_df.columns:
    sub_df["problem_id"] = sub_df["name"]
else:
    sub_df["name"] = sub_df["problem_id"]
if "full_code" in sub_df.columns:
    sub_df["code"] = sub_df["full_code"].apply(lambda t: (handle(t) or "").strip())
elif "code" not in sub_df.columns:
    print("Error: input must have 'full_code' or 'code' column", file=sys.stderr)
    sys.exit(1)
codes = sub_df[["name", "code", "problem_id"]].to_dict(orient="records")

# 异常问题：单证明 >20GB 且同题 2+ 条则整题视为异常，跳过编译并写入 results/abnormal_proofs
abnormal_path = os.path.join(parent_dir, "results", "abnormal_problems.json")
abnormal_problems = {}
if os.path.isfile(abnormal_path):
    try:
        with open(abnormal_path, "r", encoding="utf-8") as f:
            abnormal_problems = json.load(f)
    except Exception:
        pass
# 优先使用显式传入的 bench/round（由 compile_by_chunks 传入），保证异常题跳过使用正确 round
if args.bench and args.round:
    bench, round_name = args.bench, args.round
else:
    bench, round_name = _infer_bench_round(args.input_path)
abnormal_bases = set()
if not getattr(args, "no_skip_abnormal", False) and bench and round_name:
    abnormal_bases = set(abnormal_problems.get(bench, {}).get(round_name, []))
to_skip = [c for c in codes if _problem_base(c.get("problem_id") or c.get("name")) in abnormal_bases]
to_compile = [c for c in codes if c not in to_skip]
oom_list = Manager().list() if (bench and round_name) else None
# worker 数不超过待编译条数，避免子块很小时仍开满 worker
num_workers = min(num_workers, len(to_compile))
if len(to_compile) > 0 and num_workers < int(args.cpu):
    print(f"Capping workers to {num_workers} (tasks={len(to_compile)}).", file=sys.stderr)

if to_skip:
    abnormal_root = os.path.join(parent_dir, "results", "abnormal_proofs", bench, round_name)
    for c in to_skip:
        base = _problem_base(c.get("problem_id") or c.get("name"))
        pid = c.get("problem_id") or c.get("name")
        out_dir = os.path.join(abnormal_root, base)
        os.makedirs(out_dir, exist_ok=True)
        lean_path = os.path.join(out_dir, f"{pid}.lean")
        with open(lean_path, "w", encoding="utf-8") as f:
            f.write(c.get("code") or "")
    print(f"Skipped {len(to_skip)} proofs (abnormal problem), wrote to {abnormal_root}", file=sys.stderr)

    def _synthetic(c):
        return {
            "name": c["name"],
            "problem_id": c.get("problem_id", c["name"]),
            "compilation_result": {"pass": False, "complete": False, "system_errors": "abnormal_problem_skipped"},
        }

    if not to_compile:
        with open(args.output_path, "w", encoding="utf-8") as f:
            json.dump([_synthetic(c) for c in to_skip], f, indent=2, ensure_ascii=False)
        print(f"Wrote {len(to_skip)} results (all skipped) to {args.output_path}", file=sys.stderr)
        sys.exit(0)

    to_skip_set = {(c.get("problem_id") or c.get("name")) for c in to_skip}
    if num_workers == 1:
        to_compile.sort(key=lambda x: len(x.get("code") or ""))
    else:
        random.shuffle(to_compile)
    stream_path = args.output_path + ".stream.jsonl"
    scheduler(to_compile, num_workers=num_workers, timeout=args.timeout, output_stream_path=stream_path, oom_list=oom_list)
    if oom_list and len(oom_list) > 0:
        for base in list(oom_list):
            if bench not in abnormal_problems:
                abnormal_problems[bench] = {}
            if round_name not in abnormal_problems[bench]:
                abnormal_problems[bench][round_name] = []
            if base not in abnormal_problems[bench][round_name]:
                abnormal_problems[bench][round_name].append(base)
        with open(abnormal_path, "w", encoding="utf-8") as f:
            json.dump(abnormal_problems, f, indent=2, ensure_ascii=False)
        print(f"Added OOM/EOF problems to abnormal: {list(oom_list)}", file=sys.stderr)
    with open(stream_path, "r", encoding="utf-8") as fin:
        compiled = [json.loads(line) for line in fin if line.strip()]
    by_id = {(r.get("problem_id") or r.get("name")): r for r in compiled}
    result_ordered = []
    for c in codes:
        pid = c.get("problem_id") or c.get("name")
        if pid in to_skip_set:
            result_ordered.append(_synthetic(c))
        else:
            result_ordered.append(by_id[pid])
    out_dir = os.path.dirname(args.output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(result_ordered, f, indent=2, ensure_ascii=False)
    try:
        os.remove(stream_path)
    except Exception:
        pass
    print(f"Wrote {len(result_ordered)} results ({len(to_skip)} skipped) to {args.output_path}", file=sys.stderr)
    sys.exit(0)

# 单 worker 时按证明长度升序（短证明先跑），极长证明最后
if num_workers == 1:
    codes.sort(key=lambda x: len(x.get("code") or ""))
else:
    random.shuffle(codes)

out_dir = os.path.dirname(args.output_path)
if out_dir:
    os.makedirs(out_dir, exist_ok=True)
stream_path = args.output_path + ".stream.jsonl"

outputs_list = scheduler(codes, num_workers=num_workers, timeout=args.timeout, output_stream_path=stream_path, oom_list=oom_list)

if oom_list and len(oom_list) > 0 and bench and round_name:
    for base in list(oom_list):
        if bench not in abnormal_problems:
            abnormal_problems[bench] = {}
        if round_name not in abnormal_problems[bench]:
            abnormal_problems[bench][round_name] = []
        if base not in abnormal_problems[bench][round_name]:
            abnormal_problems[bench][round_name].append(base)
    with open(abnormal_path, "w", encoding="utf-8") as f:
        json.dump(abnormal_problems, f, indent=2, ensure_ascii=False)
    print(f"Added OOM/EOF problems to abnormal: {list(oom_list)}", file=sys.stderr)

if outputs_list is None:
    # 流式：从 JSONL 转为 JSON，不一次性读入内存
    if not os.path.isfile(stream_path):
        print(
            f"Error: stream file missing after scheduler: {stream_path!r} "
            f"(cwd={os.getcwd()!r}). Writer may have failed; check REPL/worker logs.",
            file=sys.stderr,
        )
        sys.exit(1)
    count = 0
    with open(stream_path, "r", encoding="utf-8") as fin:
        with open(args.output_path, "w", encoding="utf-8") as fout:
            fout.write("[\n")
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                if count > 0:
                    fout.write(",\n")
                fout.write("  ")
                fout.write(line)
                count += 1
            fout.write("\n]\n")
    try:
        os.remove(stream_path)
    except Exception:
        pass
    print(f"Wrote {count} results to {args.output_path} (streamed)", file=sys.stderr)
else:
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(outputs_list, f, indent=4)
    print(f"Wrote {len(outputs_list)} results to {args.output_path}")