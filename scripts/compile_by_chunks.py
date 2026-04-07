#!/usr/bin/env python3
"""
分块串行编译：将一轮的 to_inference_codes.json 按 chunk_size 拆成多份，
同一时间只编译其中一份（该份内用 --cpu 或按长度动态 worker 并行），
依次串行编译各块后合并结果到 code_compilation_repl.json。
用法:
  python3 scripts/compile_by_chunks.py --input_path <run_dir>/to_inference_codes.json \\
    --output_path <run_dir>/code_compilation_repl.json --chunk_size 650 --cpu 32
  # 仅跑第 12 块（0-based 11）：--chunk_index 11
  # 按块内证明长度动态减少 worker：--dynamic_workers
  # 指定块拆成子块跑（防 OOM）：SUBCHUNK_CHUNK_INDEX=57,70 SUBCHUNK_SIZE=8 将第 58、71 块各拆成 8×8 条依次编译
  # 块间内存：CHUNK_GAP_SEC、MEM_DROP_BELOW_GB、MEM_WAIT_MAX_SEC（见 main 循环）
  # 每块结束会打印 MemUsed（/proc/meminfo），便于对照 OOM
"""
import argparse
import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
COMPILE_PY = os.path.join(ZAM_LEAN, "src", "compile.py")


def get_used_gb():
    """当前整机已用内存 (GB)，读 /proc/meminfo；失败返回 None。"""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            total = avail = None
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total is not None and avail is not None:
                    return int((total - avail) / 1024 / 1024)
    except Exception:
        pass
    return None


def _code_len(item):
    """单条证明的代码长度（字符数）。"""
    return len((item.get("full_code") or item.get("code") or ""))


def _infer_bench_round_from_path(path):
    """从 output_path 推断 (bench, round_name)，用于显式传给 compile 以正确跳过异常题。"""
    p = os.path.normpath(path)
    # v2s/v2c 用 round_0 表示主轮（无 _corr1/_corr2 后缀），与 abnormal_problems 一致
    if "minif2f_v2c" in p:
        return "minif2f_v2c", "round_0"
    if "minif2f_v2s" in p:
        return "minif2f_v2s", "round_0"
    if "putnambench" in p:
        return "putnambench", "round_0"
    if "proofnet" in p:
        return "proofnet", "round_0"
    for bench in ("minif2f", "putnambench"):
        for round_name in ("round_1", "round_2", "round_3"):
            if bench in p and round_name in p:
                return bench, round_name
    return None, None


def _cpu_for_chunk(chunk, base_cpu, dynamic_workers):
    """
    根据块内证明长度决定该块使用的 worker 数。
    长证明多则少 worker，避免多进程同时跑长证明导致 OOM。
    """
    if not dynamic_workers:
        return base_cpu
    lengths = [_code_len(x) for x in chunk]
    max_len = max(lengths) if lengths else 0
    # 阈值与 worker 数可调：单条 ~20 万字符时单 worker 已可占十数 GB
    if max_len >= 150000:
        return 1
    if max_len >= 80000:
        return 2
    if max_len >= 40000:
        return 4
    if max_len >= 20000:
        return min(8, base_cpu)
    return min(base_cpu, 16)


def main():
    ap = argparse.ArgumentParser(description="Compile by chunks then merge.")
    ap.add_argument("--input_path", required=True, help="to_inference_codes.json")
    ap.add_argument("--output_path", required=True, help="code_compilation_repl.json")
    ap.add_argument("--chunk_size", type=int, default=650, help="Proofs per chunk (600-700 recommended)")
    ap.add_argument("--cpu", type=int, default=32, help="Workers per chunk (or max when --dynamic_workers)")
    ap.add_argument("--timeout", type=int, default=300, help="REPL timeout per proof")
    ap.add_argument("--keep_chunks", action="store_true", help="Keep chunk files (default when resuming); existing valid out_*.json are skipped.")
    ap.add_argument("--force", action="store_true", help="Do not skip existing out_*.json; recompile all chunks (e.g. after REPL/abbrev fix).")
    ap.add_argument("--chunk_index", type=int, default=None, help="Only run this chunk (0-based); others must already have out_*.json for merge.")
    ap.add_argument("--dynamic_workers", action="store_true", help="Set workers per chunk by max proof length (long proofs -> fewer workers).")
    ap.add_argument("--reeval-abnormal", action="store_true", help="Pass --no-skip-abnormal to compile (for re-verifying abnormal proofs).")
    args = ap.parse_args()

    if not os.path.isfile(args.input_path):
        print(f"Error: input not found: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    with open(args.input_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        print("Error: input JSON must be a list", file=sys.stderr)
        sys.exit(1)

    total = len(items)
    chunk_size = max(1, args.chunk_size)
    chunks = [items[i : i + chunk_size] for i in range(0, total, chunk_size)]
    num_chunks = len(chunks)
    print(f"Split {total} proofs into {num_chunks} chunks (size ~{chunk_size}).", file=sys.stderr)

    out_dir = os.path.dirname(args.output_path)
    base = os.path.splitext(os.path.basename(args.output_path))[0]
    chunk_dir = os.path.join(out_dir, "_chunks_" + base)
    os.makedirs(chunk_dir, exist_ok=True)
    bench, round_name = _infer_bench_round_from_path(args.output_path)
    if bench and round_name:
        print(f"Inferred bench={bench} round={round_name} (will pass to compile for abnormal skip).", file=sys.stderr)

    chunk_inputs = []
    chunk_outputs = []
    for i, chunk in enumerate(chunks):
        in_path = os.path.join(chunk_dir, f"in_{i:04d}.json")
        out_path = os.path.join(chunk_dir, f"out_{i:04d}.json")
        chunk_inputs.append(in_path)
        chunk_outputs.append(out_path)
        with open(in_path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

    chunk_gap_sec = int(os.environ.get("CHUNK_GAP_SEC", "15"))
    mem_drop_below_gb = int(os.environ.get("MEM_DROP_BELOW_GB", "0"))  # 0 = 不等待回落，仅 sleep
    mem_wait_max_sec = int(os.environ.get("MEM_WAIT_MAX_SEC", "90"))

    for i in range(num_chunks):
        if args.chunk_index is not None and i != args.chunk_index:
            continue
        expected_len = len(chunks[i])
        out_path = chunk_outputs[i]
        skip = False
        if not getattr(args, "force", False) and os.path.isfile(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) == expected_len:
                    skip = True
                    print(f"[Chunk {i+1}/{num_chunks}] Skipping (already have {expected_len} results in {os.path.basename(out_path)}).", file=sys.stderr)
            except Exception:
                pass
        if skip:
            continue
        chunk = chunks[i]
        try:
            sub_raw = os.environ.get("SUBCHUNK_CHUNK_INDEX", "-1")
            sub_indices = {int(x.strip()) for x in sub_raw.split(",") if x.strip()}
        except (ValueError, TypeError):
            sub_indices = set()
        try:
            sub_size = int(os.environ.get("SUBCHUNK_SIZE", "0"))
        except (ValueError, TypeError):
            sub_size = 0
        # 可为单块指定更小子块（如 SUBCHUNK_SIZE_57=4），防止某块即使用 8 仍 OOM
        per_chunk_key = f"SUBCHUNK_SIZE_{i}"
        try:
            per_chunk = int(os.environ.get(per_chunk_key, "0"))
            if per_chunk > 0:
                sub_size = per_chunk
                print(f"[Chunk {i+1}/{num_chunks}] Using {per_chunk_key}={per_chunk} for this chunk.", file=sys.stderr)
        except (ValueError, TypeError):
            pass
        if i in sub_indices and sub_size > 0 and len(chunk) > sub_size:
            # 将本块拆成多个子块依次编译，每子块后打点内存并 sleep，便于分析暴涨
            n_sub = (len(chunk) + sub_size - 1) // sub_size
            print(f"[Chunk {i+1}/{num_chunks}] Subchunk mode: {len(chunk)} proofs -> {n_sub} sub-chunks of ~{sub_size} (MemUsed logged per sub).", file=sys.stderr)
            sub_results = []
            for j in range(n_sub):
                start_j = j * sub_size
                sub_list = chunk[start_j : start_j + sub_size]
                mem_before = get_used_gb()
                print(f"[Chunk {i+1}/{num_chunks}] Sub {j+1}/{n_sub} start (proofs {start_j}-{start_j+len(sub_list)-1}) MemUsed={mem_before} GB", file=sys.stderr)
                sub_in = os.path.join(chunk_dir, f"_sub_{i:04d}_{j}.json")
                sub_out = os.path.join(chunk_dir, f"_sub_{i:04d}_{j}_out.json")
                with open(sub_in, "w", encoding="utf-8") as f:
                    json.dump(sub_list, f, ensure_ascii=False, indent=2)
                cpu_sub = min(_cpu_for_chunk(sub_list, args.cpu, args.dynamic_workers), len(sub_list))
                if cpu_sub < len(sub_list):
                    print(f"[Chunk {i+1}/{num_chunks}] Sub {j+1}/{n_sub}: capping workers to {cpu_sub} (sub_size={len(sub_list)}).", file=sys.stderr)
                sub_cmd = [
                    sys.executable, COMPILE_PY,
                    "--input_path", sub_in, "--output_path", sub_out,
                    "--cpu", str(cpu_sub), "--timeout", str(args.timeout),
                ]
                if bench and round_name:
                    sub_cmd += ["--bench", bench, "--round", round_name]
                if getattr(args, "reeval_abnormal", False):
                    sub_cmd += ["--no-skip-abnormal"]
                ret = subprocess.run(sub_cmd, cwd=ZAM_LEAN)
                mem_after = get_used_gb()
                print(f"[Chunk {i+1}/{num_chunks}] Sub {j+1}/{n_sub} end MemUsed={mem_after} GB (delta={mem_after - mem_before if (mem_before is not None and mem_after is not None) else '?'})", file=sys.stderr)
                if ret.returncode != 0:
                    for p in [sub_in, sub_out]:
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                    print(f"Error: chunk {i} sub {j+1}/{n_sub} failed (exit {ret.returncode}).", file=sys.stderr)
                    sys.exit(ret.returncode)
                with open(sub_out, "r", encoding="utf-8") as f:
                    sub_results.extend(json.load(f))
                for p in [sub_in, sub_out]:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                if j < n_sub - 1:
                    time.sleep(chunk_gap_sec)
                    mem_after_sleep = get_used_gb()
                    print(f"[Chunk {i+1}/{num_chunks}] After sub {j+1}/{n_sub} sleep {chunk_gap_sec}s MemUsed={mem_after_sleep} GB", file=sys.stderr)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(sub_results, f, ensure_ascii=False, indent=2)
            print(f"[Chunk {i+1}/{num_chunks}] Subchunk done: {len(sub_results)} results -> {os.path.basename(out_path)}", file=sys.stderr)
            continue
        cpu = min(_cpu_for_chunk(chunk, args.cpu, args.dynamic_workers), len(chunk))
        if cpu < len(chunk):
            print(f"[Chunk {i+1}/{num_chunks}] Capping workers to {cpu} (chunk_size={len(chunk)}).", file=sys.stderr)
        if args.dynamic_workers:
            max_len = max(_code_len(x) for x in chunks[i])
            print(f"[Chunk {i+1}/{num_chunks}] max_code_len={max_len}, using {cpu} workers.", file=sys.stderr)
        if i > 0:
            print(f"Waiting {chunk_gap_sec}s for previous chunk processes to exit...", file=sys.stderr)
            time.sleep(chunk_gap_sec)
            if mem_drop_below_gb > 0:
                waited = 0
                while waited < mem_wait_max_sec:
                    used = get_used_gb()
                    if used is not None and used < mem_drop_below_gb:
                        print(f"MemUsed {used} GB < {mem_drop_below_gb} GB, starting next chunk.", file=sys.stderr)
                        break
                    if used is not None:
                        print(f"MemUsed {used} GB (target < {mem_drop_below_gb} GB), waiting 10s...", file=sys.stderr)
                    time.sleep(10)
                    waited += 10
                if waited >= mem_wait_max_sec:
                    print(f"Waited {mem_wait_max_sec}s, starting next chunk anyway.", file=sys.stderr)
        mem_start = get_used_gb()
        print(
            f"[Chunk {i+1}/{num_chunks}] Compiling {expected_len} proofs (cpu={cpu}) MemUsed={mem_start} GB",
            file=sys.stderr,
        )
        cmd = [
            sys.executable,
            COMPILE_PY,
            "--input_path", chunk_inputs[i],
            "--output_path", out_path,
            "--cpu", str(cpu),
            "--timeout", str(args.timeout),
        ]
        if bench and round_name:
            cmd += ["--bench", bench, "--round", round_name]
        if getattr(args, "reeval_abnormal", False):
            cmd += ["--no-skip-abnormal"]
        ret = subprocess.run(cmd, cwd=ZAM_LEAN)
        mem_end = get_used_gb()
        if mem_start is not None and mem_end is not None:
            print(
                f"[Chunk {i+1}/{num_chunks}] done MemUsed={mem_end} GB (delta {mem_end - mem_start:+d} GB)",
                file=sys.stderr,
            )
        else:
            print(f"[Chunk {i+1}/{num_chunks}] done MemUsed={mem_end} GB", file=sys.stderr)
        if ret.returncode != 0:
            print(f"Error: chunk {i} compile failed (exit {ret.returncode}).", file=sys.stderr)
            sys.exit(ret.returncode)

    if args.chunk_index is not None:
        print(f"Chunk {args.chunk_index + 1} done. Output: {chunk_outputs[args.chunk_index]}", file=sys.stderr)
        print("Run without --chunk_index to merge all chunks into output_path.", file=sys.stderr)
        return

    merged = []
    for out_path in chunk_outputs:
        if not os.path.isfile(out_path):
            print(f"Error: missing {out_path}", file=sys.stderr)
            sys.exit(1)
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged.extend(data)

    os.makedirs(out_dir, exist_ok=True)
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Merged {len(merged)} results -> {args.output_path}", file=sys.stderr)

    if not args.keep_chunks:
        for p in chunk_inputs + chunk_outputs:
            try:
                os.remove(p)
            except Exception:
                pass
        try:
            os.rmdir(chunk_dir)
        except Exception:
            pass
    else:
        print(f"Chunk files kept in {chunk_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
