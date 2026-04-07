#!/usr/bin/env python3
"""
Smoke test: load several benchmarks, verify statements compile with sorry in REPL,
optionally run whole_proof (Goedel) on a few problems per dataset.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Allow `python prover/cross_dataset_smoke.py` from repo root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prover.config import ModelConfig, ProverConfig, VerifierConfig, WholeProofConfig
from prover.datasets import Problem, load_dataset
from prover.engine import ProofSearchEngine
from prover.strategies.base import ProofStrategy


def strip_for_repl(code: str) -> str:
    return ProofStrategy.strip_imports(code)


def normalize_stmt(code: str) -> str:
    """Putnam-style `:=\\n  sorry` -> `:= by sorry` for whole-proof prompts."""
    return re.sub(r":=\s*\n\s*sorry\b", ":= by sorry", code, flags=re.MULTILINE)


def run_verify_only(args) -> int:
    from prover.verifier import LeanVerifier

    cfg = VerifierConfig(mathlib_path=args.mathlib)
    v = LeanVerifier(cfg)
    v.start()
    rows = []
    try:
        for ds in args.datasets:
            try:
                problems = load_dataset(ds, limit=args.per_dataset)
            except Exception as e:
                rows.append({"dataset": ds, "error": str(e)})
                print(f"[{ds}] load error: {e}")
                continue
            print(f"\n=== {ds} ({len(problems)} problems) ===")
            for p in problems:
                code = strip_for_repl(p.lean4_code)
                t0 = time.time()
                r = v.verify(code)
                elapsed = time.time() - t0
                row = {
                    "dataset": ds,
                    "problem_id": p.problem_id,
                    "pass": r.success,
                    "complete": r.complete,
                    "n_sorry": len(r.sorries),
                    "n_errors": len(r.errors),
                    "elapsed": round(elapsed, 2),
                    "system_error": r.system_error,
                }
                rows.append(row)
                st = "OK" if r.success else "FAIL"
                print(
                    f"  {st} {p.problem_id}  sorry={len(r.sorries)} err={len(r.errors)} "
                    f"{elapsed:.1f}s"
                )
                if not r.success and r.errors:
                    print(f"    first: {r.errors[0].get('data', '')[:120]}")
    finally:
        v.stop()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    n_ok = sum(1 for x in rows if x.get("pass"))
    n_tot = sum(1 for x in rows if "problem_id" in x)
    print(f"\nWrote {out}  pass={n_ok}/{n_tot}")
    return 0 if n_ok == n_tot else 1


def _prepare_problem(p: Problem) -> Problem:
    code = normalize_stmt(strip_for_repl(p.lean4_code))
    if ":= by" not in code and "sorry" in code.lower():
        code = re.sub(r":=\s*(by\s+)?sorry", ":= by sorry", code, flags=re.I)
    hdr = ProofStrategy.extract_theorem_header(code)
    if not any(k in hdr for k in ("theorem", "lemma", "example", "abbrev")):
        hdr = code.split(":= by")[0].strip() + " := by" if ":=" in code else hdr
    return Problem(
        problem_id=p.problem_id,
        name=p.name,
        lean4_code=code,
        formal_statement=code,
        theorem_header=hdr,
        informal_statement=p.informal_statement,
        split=p.split,
        source=p.source,
        tags=p.tags,
    )


def run_with_model(args) -> int:
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    if args.cuda_devices:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.cuda_devices

    config = ProverConfig(
        model=ModelConfig(
            model_path=args.model_path,
            tensor_parallel_size=args.tp,
            max_model_len=args.max_model_len,
            max_tokens=args.max_tokens,
            temperature=args.temp,
            use_chat_template=args.use_chat,
        ),
        verifier=VerifierConfig(mathlib_path=args.mathlib),
        whole_proof=WholeProofConfig(samples_per_problem=args.samples, use_cot=False),
        strategies=["whole_proof"],
        output_dir=args.output_dir,
        cuda_devices=args.cuda_devices or "",
    )
    engine = ProofSearchEngine(config)
    engine.setup()
    summary = []
    try:
        for ds in args.datasets:
            problems = load_dataset(ds, limit=args.prove_per_dataset)
            print(f"\n>>> whole_proof on {ds} ({len(problems)} problems)")
            for p in problems:
                p2 = _prepare_problem(p)
                t0 = time.time()
                att = engine.prove_one(p2)
                dt = time.time() - t0
                summary.append({
                    "dataset": ds,
                    "problem_id": p.problem_id,
                    "complete": att.complete,
                    "attempts": att.attempts,
                    "seconds": round(dt, 1),
                })
                print(
                    f"  {p.problem_id}: complete={att.complete} "
                    f"attempts={att.attempts} ({dt:.1f}s)"
                )
    finally:
        engine.teardown()
    out = Path(args.output_dir) / "cross_dataset_llm_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Cross-dataset smoke / LLM test")
    ap.add_argument(
        "--datasets",
        nargs="+",
        default=[
            "minif2f",
            "proofnet",
            "putnambench",
            "fate_h",
            "fate_m",
            "fate_x",
        ],
    )
    ap.add_argument("--per-dataset", type=int, default=3)
    ap.add_argument("--mathlib", default="mathlib4")
    ap.add_argument("--output", default="results/prover/cross_dataset_verify.json")
    ap.add_argument("--with-model", action="store_true", help="Run Goedel whole_proof")
    ap.add_argument("--prove-per-dataset", type=int, default=2)
    ap.add_argument("--model-path", default="Goedel-LM/Goedel-Prover-V2-8B")
    ap.add_argument("--tp", type=int, default=2)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--max-model-len", type=int, default=4096)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--temp", type=float, default=0.7)
    ap.add_argument("--cuda-devices", default="0,1")
    ap.add_argument(
        "--use-chat",
        action="store_true",
        help="Use tokenizer chat template (off by default for Goedel)",
    )
    ap.add_argument("--output-dir", default="results/prover/cross_dataset_llm")
    args = ap.parse_args()

    rc = run_verify_only(args)
    if args.with_model:
        rc = run_with_model(args) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
