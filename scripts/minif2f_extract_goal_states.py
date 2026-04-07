#!/usr/bin/env python3
"""对 sorry 子问题提取 goal state，并生成“独立上下文”子题。

实现方式：复用已有 compile_by_chunks（更稳），从 compilation_result.sorries 抽取目标态。
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple


def parse_goal_text(goal_text: str) -> Tuple[List[str], str]:
    """
    将 sorries.goal 文本拆分为 local context 与 target。
    预期形态:
      x y : Nat
      h : x = y
      ⊢ y = x
    """
    if not goal_text:
        return [], ""
    lines = [ln.rstrip() for ln in goal_text.splitlines() if ln.strip()]
    target = ""
    ctx = []
    for ln in lines:
        if ln.strip().startswith("⊢"):
            target = ln.split("⊢", 1)[1].strip()
        else:
            ctx.append(ln.strip())
    return ctx, target


def ctx_lines_to_decls(ctx_lines: List[str]) -> List[str]:
    decls = []
    for ln in ctx_lines:
        if ":" not in ln:
            continue
        left, right = ln.split(":", 1)
        left = left.strip()
        right = right.strip()
        if not left or not right:
            continue
        # 统一用 variable 声明，保留原名称与类型
        decls.append(f"variable ({left} : {right})")
    return decls


def build_independent_code(sub_id: str, ctx_lines: List[str], target: str) -> Optional[str]:
    if not target:
        return None
    thm_name = re.sub(r"[^A-Za-z0-9_]", "_", sub_id)
    decls = ctx_lines_to_decls(ctx_lines)
    prefix = "\n".join(decls)
    if prefix:
        prefix += "\n\n"
    return (
        "import Mathlib\nimport Aesop\n\n"
        + prefix
        + f"theorem {thm_name} : {target} := by\n"
        + "  sorry\n"
    )


def extract_theorem_signature(code: str) -> Tuple[str, str]:
    """
    从代码中提取 theorem/lemma 的 binder 与目标类型。
    返回 (binders, target)，失败则返回 ("","")
    """
    if not code:
        return "", ""
    # 仅匹配到 := by 之前，避免跨到证明体
    m = re.search(
        r"(?:^|\n)\s*(theorem|lemma)\s+[A-Za-z0-9_']+\s*(.*?)\s*:\s*(.*?)\s*:=\s*by",
        code,
        flags=re.S,
    )
    if not m:
        return "", ""
    binders = (m.group(2) or "").strip()
    target = (m.group(3) or "").strip()
    return binders, target


def first_sorry_goal(compilation_result: Dict) -> Optional[str]:
    sorries = (compilation_result or {}).get("sorries") or []
    if not sorries:
        return None
    s0 = sorries[0]
    if isinstance(s0, dict):
        # 常见字段名兼容
        return s0.get("goal") or s0.get("type") or s0.get("data")
    if isinstance(s0, str):
        return s0
    return None


def main():
    ap = argparse.ArgumentParser(description="Extract goal states from sorry subproblems.")
    ap.add_argument("--input_manifest", required=True)
    ap.add_argument("--output_manifest", required=True)
    ap.add_argument("--output_dataset_jsonl", required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 means all")
    args = ap.parse_args()

    with open(args.input_manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    if args.limit and args.limit > 0:
        manifest = manifest[: args.limit]

    out_manifest = []
    ds_lines = []

    # 先把 patched_code 作为临时输入，用 compile_by_chunks 统一编译并收集 sorries
    with tempfile.TemporaryDirectory(prefix="subproblem_goal_") as td:
        in_json = os.path.join(td, "codes.json")
        out_json = os.path.join(td, "compiled.json")
        compile_items = []
        for m in manifest:
            sub_id = m.get("subproblem_id")
            code = m.get("patched_code") or ""
            if not sub_id or not code:
                continue
            compile_items.append({"problem_id": sub_id, "name": sub_id, "code": code})
        with open(in_json, "w", encoding="utf-8") as f:
            json.dump(compile_items, f, ensure_ascii=False)

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cmd = [
            "python3",
            "scripts/compile_by_chunks.py",
            "--input_path", in_json,
            "--output_path", out_json,
            "--chunk_size", "20",
            "--cpu", "1",
            "--timeout", "180",
            "--keep_chunks",
        ]
        print("Running:", " ".join(cmd), flush=True)
        subprocess.run(cmd, cwd=root, check=True)

        with open(out_json, "r", encoding="utf-8") as f:
            compiled = json.load(f)
        comp_by_id = {r.get("problem_id") or r.get("name"): r for r in compiled}

        for i, m in enumerate(manifest, start=1):
            sub_id = m.get("subproblem_id")
            row = comp_by_id.get(sub_id, {})
            comp = row.get("compilation_result", {})
            goal_text = first_sorry_goal(comp)
            ctx_lines, target = parse_goal_text(goal_text or "")
            indep_code = build_independent_code(sub_id, ctx_lines, target)
            # 退化策略：若 sorries 里拿不到 goal，则回退到 theorem 声明目标
            if not indep_code:
                binders, fallback_target = extract_theorem_signature(m.get("patched_code") or m.get("original_code") or "")
                if fallback_target:
                    thm_name = re.sub(r"[^A-Za-z0-9_]", "_", sub_id)
                    indep_code = (
                        "import Mathlib\nimport Aesop\n\n"
                        + f"theorem {thm_name} {binders} : {fallback_target} := by\n"
                        + "  sorry\n"
                    )

            merged = dict(m)
            merged["goal_state"] = {
                "raw": goal_text,
                "local_context": ctx_lines,
                "target": target,
            }
            merged["independent_code"] = indep_code
            merged["goal_extracted"] = bool(indep_code)
            out_manifest.append(merged)

            if indep_code:
                ds_lines.append(
                    json.dumps(
                        {
                            "problem_id": sub_id,
                            "origin_problem_id": m.get("problem_id"),
                            "lean4_code": indep_code,
                        },
                        ensure_ascii=False,
                    )
                )
            if i % 50 == 0:
                print(f"Processed {i}/{len(manifest)} subproblems...", flush=True)

    os.makedirs(os.path.dirname(args.output_manifest), exist_ok=True)
    os.makedirs(os.path.dirname(args.output_dataset_jsonl), exist_ok=True)
    with open(args.output_manifest, "w", encoding="utf-8") as f:
        json.dump(out_manifest, f, ensure_ascii=False, indent=2)
    with open(args.output_dataset_jsonl, "w", encoding="utf-8") as f:
        if ds_lines:
            f.write("\n".join(ds_lines) + "\n")
        else:
            f.write("")

    extracted = sum(1 for x in out_manifest if x.get("goal_extracted"))
    print(f"Wrote {len(out_manifest)} entries -> {args.output_manifest}")
    print(f"Goal extracted: {extracted}/{len(out_manifest)}")
    print(f"Wrote {len(ds_lines)} dataset lines -> {args.output_dataset_jsonl}")


if __name__ == "__main__":
    main()
