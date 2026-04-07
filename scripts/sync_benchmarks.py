#!/usr/bin/env python3
"""
从 lean-benchmark (https://github.com/ZZZamchi/lean-benchmark) 同步基准数据，
转换为 Zam 推理/编译所需的 JSONL 格式（含 name, problem_id, lean4_code, formal_statement, informal_prefix, split）。
用法:
  python3 scripts/sync_benchmarks.py [--benchmark-root PATH] [--dataset-dir PATH] [--bench BENCH1 BENCH2 ...]
默认 benchmark-root=../lean-benchmark（与 Zam/lean 同级），dataset-dir=../dataset，bench=minif2f,putnambench。
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DEFAULT_BENCHMARK_ROOT = os.path.abspath(os.path.join(ZAM_LEAN, "..", "lean-benchmark"))
DEFAULT_DATASET_DIR = os.path.join(ZAM_LEAN, "dataset")

# Zam 推理用的标准 header（与现有 minif2f 一致）
ZAM_HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"


def zam_record(name: str, lean4_code: str, formal_statement: str, informal_prefix: str, split: str = "test") -> dict:
    return {
        "name": name,
        "problem_id": name,
        "lean4_code": lean4_code,
        "formal_statement": formal_statement,
        "informal_prefix": informal_prefix,
        "split": split,
    }


def sync_minif2f(bench_root: str, out_path: str, version: str = "") -> int:
    """从 lean-benchmark benchmarks/minif2f 生成 Zam 格式 JSONL。version 为空时优先 v2c 否则 v2s；v2c/v2s 指定只用其一。"""
    datasets = os.path.join(bench_root, "benchmarks", "minif2f", "datasets")
    if not os.path.isdir(datasets):
        print(f"Skip minif2f: not found {datasets}", file=sys.stderr)
        return 0
    if version and version.lower() in ("v2c", "v2s"):
        order = ["miniF2F_v2c"] if version.lower() == "v2c" else ["miniF2F_v2s"]
    else:
        order = ["miniF2F_v2c", "miniF2F_v2s"]
    for name in order:
        src = os.path.join(datasets, f"{name}.jsonl")
        if not os.path.isfile(src):
            continue
        count = 0
        with open(src, "r", encoding="utf-8") as f_in, open(out_path, "w", encoding="utf-8") as f_out:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                name_id = obj.get("name", "")
                formal = obj.get("formal_statement", "").strip()
                header = obj.get("header", ZAM_HEADER).strip()
                if not header.endswith("\n"):
                    header += "\n"
                informal = obj.get("informal_statement", "")
                if not informal.endswith("\n"):
                    informal += "\n"
                # lean4_code = header + formal + " sorry"（若 formal 已含 := by 且无 sorry）
                if "sorry" not in formal:
                    formal_for_code = formal + " sorry" if formal.rstrip().endswith("by") else formal + " := by sorry"
                else:
                    formal_for_code = formal
                lean4_code = header + formal_for_code
                rec = zam_record(name_id, lean4_code, formal, informal, obj.get("split", "test"))
                f_out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1
        print(f"minif2f: wrote {count} records to {out_path} from {src}", file=sys.stderr)
        return count
    print("Skip minif2f: no miniF2F_v2c.jsonl or miniF2F_v2s.jsonl", file=sys.stderr)
    return 0


def extract_lean_theorems(lean_dir: str):
    """从 putnambench lean4/src 递归提取 theorem ... sorry 及 name。"""
    lean_regex = re.compile(r"((?:abbrev[\s\S]+?)?theorem\s+(\S+)[\s\S]+?sorry)", re.MULTILINE)
    theorems = []
    for root, _dirs, files in os.walk(lean_dir):
        for f in files:
            if not f.endswith(".lean"):
                continue
            path = os.path.join(root, f)
            try:
                text = open(path, "r", encoding="utf-8").read()
            except Exception:
                continue
            for m in lean_regex.finditer(text):
                full_statement = m.group(1).strip()
                thm_name = m.group(2).strip()
                theorems.append({"name": thm_name, "lean4_statement": full_statement})
    return theorems


def sync_putnambench(bench_root: str, out_path: str) -> int:
    """从 lean-benchmark benchmarks/putnambench 生成 Zam 格式 JSONL。"""
    putnam_root = os.path.join(bench_root, "benchmarks", "putnambench")
    informal_path = os.path.join(putnam_root, "informal", "putnam.json")
    lean4_src = os.path.join(putnam_root, "lean4", "src")
    if not os.path.isdir(lean4_src):
        print(f"Skip putnambench: not found {lean4_src}", file=sys.stderr)
        return 0
    theorems = extract_lean_theorems(lean4_src)
    informal_map = {}
    if os.path.isfile(informal_path):
        with open(informal_path, "r", encoding="utf-8") as f:
            for obj in json.load(f):
                informal_map[obj.get("problem_name", "")] = obj.get("informal_statement", "")
    count = 0
    with open(out_path, "w", encoding="utf-8") as f_out:
        for thm in theorems:
            name = thm["name"]
            lean4_statement = thm.get("lean4_statement", "")
            if not lean4_statement or "sorry" not in lean4_statement:
                continue
            informal = informal_map.get(name, "")
            if not informal.endswith("\n"):
                informal += "\n"
            # formal_statement：仅定理签名（到 := 或 sorry 前一行），用于 prompt
            formal = lean4_statement.split("sorry")[0].strip().rstrip()
            if formal.endswith(":="):
                formal = formal[:-2].strip()
            lean4_code = ZAM_HEADER + lean4_statement
            rec = zam_record(name, lean4_code, formal, informal, "test")
            f_out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    print(f"putnambench: wrote {count} records to {out_path}", file=sys.stderr)
    return count


def sync_proofnet(bench_root: str, out_path: str) -> int:
    """从 lean-benchmark benchmarks/proofnet/benchmark 的 test.jsonl + valid.jsonl 生成 Zam 格式 JSONL。"""
    bench_dir = os.path.join(bench_root, "benchmarks", "proofnet", "benchmark")
    test_path = os.path.join(bench_dir, "test.jsonl")
    valid_path = os.path.join(bench_dir, "valid.jsonl")
    if not os.path.isfile(test_path):
        print(f"Skip proofnet: not found {test_path}", file=sys.stderr)
        return 0
    count = 0
    with open(out_path, "w", encoding="utf-8") as f_out:
        for path, split in [(valid_path, "valid"), (test_path, "test")]:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as f_in:
                for line in f_in:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    name = obj.get("id", "").strip()
                    formal = (obj.get("formal_statement") or "").strip()
                    informal = (obj.get("nl_statement") or "").strip()
                    if not name or not formal:
                        continue
                    if not informal.endswith("\n"):
                        informal += "\n"
                    if "sorry" not in formal:
                        if formal.rstrip().endswith(":="):
                            formal_for_code = formal + " by sorry"
                        else:
                            formal_for_code = formal + " := by sorry"
                    else:
                        formal_for_code = formal
                    lean4_code = ZAM_HEADER + formal_for_code
                    rec = zam_record(name, lean4_code, formal, informal, split)
                    f_out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    count += 1
    print(f"proofnet: wrote {count} records to {out_path}", file=sys.stderr)
    return count


def main():
    ap = argparse.ArgumentParser(description="Sync lean-benchmark data to Zam dataset JSONL.")
    ap.add_argument("--benchmark-root", default=DEFAULT_BENCHMARK_ROOT, help="Path to lean-benchmark repo")
    ap.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR, help="Output dataset directory under Zam/lean")
    ap.add_argument("--bench", nargs="*", default=["minif2f", "putnambench"], choices=["minif2f", "putnambench", "proofnet"], help="Benchmarks to sync")
    ap.add_argument("--minif2f-version", choices=["v2c", "v2s"], default="", help="Use only v2c or v2s for minif2f; default=auto (v2c then v2s)")
    ap.add_argument("--skip-existing", action="store_true", help="Skip writing if output file already exists")
    args = ap.parse_args()
    if not os.path.isdir(args.benchmark_root):
        print(f"Error: benchmark root not found: {args.benchmark_root}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(args.dataset_dir, exist_ok=True)
    for bench in args.bench:
        if bench == "minif2f" and getattr(args, "minif2f_version", None):
            out_path = os.path.join(args.dataset_dir, f"minif2f_{args.minif2f_version}.jsonl")
        else:
            out_path = os.path.join(args.dataset_dir, f"{bench}.jsonl")
        if args.skip_existing and os.path.isfile(out_path):
            print(f"Skip {out_path} (already exists).", file=sys.stderr)
            continue
        if bench == "minif2f":
            sync_minif2f(args.benchmark_root, out_path, version=getattr(args, "minif2f_version", "") or "")
        elif bench == "putnambench":
            sync_putnambench(args.benchmark_root, out_path)
        elif bench == "proofnet":
            sync_proofnet(args.benchmark_root, out_path)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
