#!/usr/bin/env python3
"""
将 lean-benchmark 中所有数据集导入到 Zam/lean/dataset/，已有文件不覆盖。
- 对 minif2f / putnambench 调用 sync_benchmarks 转为 Zam JSONL（--skip-existing）。
- 对其余数据集（minif2f_v1、proofnet、fate、leancat）直接复制到 dataset/，已存在则跳过。
用法: python3 scripts/import_all_benchmarks.py [--benchmark-root PATH] [--dataset-dir PATH]
"""
import argparse
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DEFAULT_BENCHMARK_ROOT = os.path.abspath(os.path.join(ZAM_LEAN, "..", "lean-benchmark"))
DEFAULT_DATASET_DIR = os.path.join(ZAM_LEAN, "dataset")


def copy_if_missing(src: str, dst: str, desc: str = "") -> bool:
    if not os.path.isfile(src):
        print(f"Skip {desc or dst}: source not found {src}", file=sys.stderr)
        return False
    if os.path.isfile(dst):
        print(f"Skip {dst} (already exists).", file=sys.stderr)
        return False
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied -> {dst}", file=sys.stderr)
    return True


def main():
    ap = argparse.ArgumentParser(description="Import all lean-benchmark datasets into Zam/lean/dataset.")
    ap.add_argument("--benchmark-root", default=DEFAULT_BENCHMARK_ROOT, help="Path to lean-benchmark repo")
    ap.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR, help="Output directory (default: dataset/)")
    args = ap.parse_args()
    bench_root = os.path.abspath(args.benchmark_root)
    dataset_dir = os.path.abspath(args.dataset_dir)
    if not os.path.isdir(bench_root):
        print(f"Error: benchmark root not found: {bench_root}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(dataset_dir, exist_ok=True)

    # 1) 通过 sync_benchmarks 同步 minif2f / putnambench（已有则跳过）
    sync_script = os.path.join(ZAM_LEAN, "scripts", "sync_benchmarks.py")
    for bench_spec in [
        ["--bench", "minif2f"],
        ["--bench", "minif2f", "--minif2f-version", "v2c"],
        ["--bench", "minif2f", "--minif2f-version", "v2s"],
        ["--bench", "putnambench"],
    ]:
        cmd = [
            sys.executable, sync_script,
            "--benchmark-root", bench_root,
            "--dataset-dir", dataset_dir,
            "--skip-existing",
        ] + bench_spec
        subprocess.run(cmd, cwd=ZAM_LEAN, check=False)

    # 2) 复制其余数据集到 dataset/，已存在则跳过
    copies = [
        (os.path.join(bench_root, "benchmarks", "minif2f", "minif2f_v1", "miniF2F_v1.json"),
        os.path.join(dataset_dir, "minif2f_v1.json")),
        (os.path.join(bench_root, "benchmarks", "proofnet", "benchmark", "valid.jsonl"),
        os.path.join(dataset_dir, "proofnet_valid.jsonl")),
        (os.path.join(bench_root, "benchmarks", "proofnet", "benchmark", "test.jsonl"),
        os.path.join(dataset_dir, "proofnet_test.jsonl")),
        (os.path.join(bench_root, "benchmarks", "fate", "FATE-X", "FATE-X.json"),
        os.path.join(dataset_dir, "fate_FATE-X.json")),
        (os.path.join(bench_root, "benchmarks", "fate", "FATE-H", "FATE-H.json"),
        os.path.join(dataset_dir, "fate_FATE-H.json")),
        (os.path.join(bench_root, "benchmarks", "fate", "FATE-M", "FATE-M.json"),
        os.path.join(dataset_dir, "fate_FATE-M.json")),
        (os.path.join(bench_root, "benchmarks", "leancat", "metadata.json"),
        os.path.join(dataset_dir, "leancat_metadata.json")),
    ]
    for src, dst in copies:
        copy_if_missing(src, dst)

    print("Import done.", file=sys.stderr)


if __name__ == "__main__":
    main()
