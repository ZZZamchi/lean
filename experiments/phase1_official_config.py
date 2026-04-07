#!/usr/bin/env python3
"""
Phase 1: Run Goedel-8B with OFFICIAL configuration on unsolved problems.

Key fixes vs previous runs:
  1. Chat template ENABLED (model was trained with chat format)
  2. max_tokens=32768 (official uses 32K, we had 4096)
  3. Official Goedel prompt format
  4. Batch generation to avoid KV cache OOM

Usage:
  python3 experiments/phase1_official_config.py --gpus 2,3 --samples 32
  python3 experiments/phase1_official_config.py --gpus 2,3 --samples 32 --self-correction 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOEDEL_PROMPT = """\
Complete the following Lean 4 code:

```lean4
{formal_statement}```

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof."""

SELF_CORRECTION_PROMPT = """\
The following Lean 4 proof attempt failed compilation:

```lean4
{failed_code}
```

The Lean compiler reported the following errors:
```
{error_messages}
```

Please fix the proof. First analyze what went wrong, then provide a corrected complete proof.

```lean4
{formal_statement}```"""


def assemble_code(header, extracted, strip_imports_fn):
    if "theorem" in extracted and ":= by" in extracted:
        return strip_imports_fn(extracted)
    if extracted.strip().startswith("by"):
        return f"{header.rstrip()}\n{extracted}"
    return f"{header}\n  {extracted}"


def run_official(gpus: str, samples: int = 32, self_correction_rounds: int = 0):
    from prover.config import ModelConfig, VerifierConfig
    from prover.datasets import load_dataset
    from prover.model import ProverModel
    from prover.strategies.base import ProofStrategy
    from prover.verifier import LeanVerifier

    out_dir = ROOT / "results" / "experiments" / "phase1_official"
    os.makedirs(out_dir, exist_ok=True)

    mcfg = ModelConfig(
        model_path="Goedel-LM/Goedel-Prover-V2-8B",
        tensor_parallel_size=2,
        max_model_len=32768,
        max_tokens=32768,
        temperature=1.0,
        top_p=0.95,
        gpu_memory_utilization=0.92,
        use_chat_template=True,
    )

    os.environ["CUDA_VISIBLE_DEVICES"] = gpus
    model = ProverModel(mcfg, cuda_devices=gpus)
    model.load()

    verifier = LeanVerifier(VerifierConfig(mathlib_path="mathlib4"))
    verifier.start()

    problems = load_dataset("minif2f_unsolved39")
    results = []
    solved_count = 0
    batch_size = 4

    try:
        for idx, prob in enumerate(problems):
            t0 = time.time()
            print(f"\n[{idx+1}/{len(problems)}] {prob.problem_id}")

            stmt = prob.lean4_code
            header = ProofStrategy.strip_imports(prob.theorem_header)
            prompt = GOEDEL_PROMPT.format(formal_statement=stmt)

            attempt = {
                "problem_id": prob.problem_id,
                "complete": False,
                "attempts": 0,
                "strategy": "phase1_official",
                "code": "",
                "self_correction_rounds": 0,
            }
            best_error_code = None
            best_error_msg = None

            for batch_start in range(0, samples, batch_size):
                batch_n = min(batch_size, samples - batch_start)
                batch_out = model.generate_single(
                    prompt, n=batch_n, temperature=1.0,
                    max_tokens=32768, chat=True,
                )

                for raw in batch_out:
                    extracted = model.extract_lean_code(raw)
                    if not extracted:
                        continue
                    code = assemble_code(header, extracted, ProofStrategy.strip_imports)
                    attempt["attempts"] += 1
                    r = verifier.verify(code)

                    if r.complete:
                        attempt["complete"] = True
                        attempt["code"] = code
                        break

                    if r.success and not r.complete and best_error_code is None:
                        best_error_code = code
                        best_error_msg = "; ".join(
                            s.get("goal", "")[:100] for s in r.sorries[:3]
                        )
                    elif r.errors and best_error_code is None:
                        best_error_code = code
                        best_error_msg = "; ".join(
                            e.get("data", "")[:100] for e in r.errors[:3]
                        )

                if attempt["complete"]:
                    break

            if not attempt["complete"] and self_correction_rounds > 0 and best_error_code:
                for sc_round in range(1, self_correction_rounds + 1):
                    print(f"  Self-correction round {sc_round}...")
                    sc_prompt = SELF_CORRECTION_PROMPT.format(
                        failed_code=best_error_code,
                        error_messages=best_error_msg or "unknown error",
                        formal_statement=stmt,
                    )
                    sc_n = min(samples // 2, 8)
                    sc_outputs = model.generate_single(
                        sc_prompt, n=sc_n,
                        temperature=0.8, max_tokens=32768, chat=True,
                    )
                    for raw in sc_outputs:
                        extracted = model.extract_lean_code(raw)
                        if not extracted:
                            continue
                        code = assemble_code(header, extracted, ProofStrategy.strip_imports)
                        attempt["attempts"] += 1
                        r = verifier.verify(code)
                        if r.complete:
                            attempt["complete"] = True
                            attempt["code"] = code
                            attempt["self_correction_rounds"] = sc_round
                            break
                        if r.errors:
                            best_error_code = code
                            best_error_msg = "; ".join(
                                e.get("data", "")[:100] for e in r.errors[:3]
                            )
                    if attempt["complete"]:
                        break

            elapsed = time.time() - t0
            attempt["elapsed"] = round(elapsed, 1)

            if attempt["complete"]:
                solved_count += 1
                sc_info = f" (SC round {attempt['self_correction_rounds']})" if attempt["self_correction_rounds"] > 0 else ""
                print(f"  [SOLVED] in {elapsed:.1f}s, {attempt['attempts']} attempts{sc_info}")
            else:
                print(f"  [FAIL] in {elapsed:.1f}s, {attempt['attempts']} attempts")

            results.append(attempt)
            with open(out_dir / "proof_results.json", "w") as f:
                json.dump(results, f, indent=2)

    finally:
        verifier.stop()

    print(f"\n{'='*60}")
    print(f"Phase 1 Official Config: {solved_count}/{len(problems)} newly solved")
    print(f"Baseline was 205/244 = 84.0%")
    new_total = 205 + solved_count
    print(f"Projected: {new_total}/244 = {100*new_total/244:.1f}%")
    solved_pids = [r["problem_id"] for r in results if r["complete"]]
    if solved_pids:
        print(f"Solved: {solved_pids}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gpus", type=str, default="2,3")
    p.add_argument("--samples", type=int, default=32)
    p.add_argument("--self-correction", type=int, default=0)
    args = p.parse_args()
    run_official(args.gpus, args.samples, args.self_correction)


if __name__ == "__main__":
    main()
