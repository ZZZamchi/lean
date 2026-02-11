"""批量编译第一轮/第二轮推理结果：读 to_inference_codes.json，经 REPL 验证后写 code_compilation_repl.json。"""
import argparse
import json
import os
import random
import sys

import pandas as pd

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from lean_compiler.repl_scheduler import scheduler


def handle(text):
    """去掉 full_code 中的 import/set_option/open 行，只保留定理与证明。"""
    if not text or not isinstance(text, str):
        return ""
    lines = text.split("\n")
    filtered = [
        line for line in lines
        if not line.strip().startswith(("import", "set_option", "open"))
    ]
    return "\n".join(filtered).strip()


parser = argparse.ArgumentParser(description="Compile Lean proofs via REPL.")
parser.add_argument("--input_path", required=True, type=str, help="to_inference_codes.json")
parser.add_argument("--output_path", required=True, type=str, help="code_compilation_repl.json")
parser.add_argument("--cpu", default=64, type=int, help="Number of REPL workers")
args = parser.parse_args()

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
random.shuffle(codes)

outputs_list = scheduler(codes, num_workers=args.cpu)

out_dir = os.path.dirname(args.output_path)
if out_dir:
    os.makedirs(out_dir, exist_ok=True)
with open(args.output_path, "w", encoding="utf-8") as f:
    json.dump(outputs_list, f, indent=4)
print(f"Wrote {len(outputs_list)} results to {args.output_path}")