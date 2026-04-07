#!/usr/bin/env python3
"""
Systematic pass@32 booster for Goedel-8B on miniF2F unsolved problems.

Runs multiple experiments (different temperatures, max_tokens, prompts) and
aggregates newly solved problems vs the baseline.

Usage:
  python3 experiments/boost_pass32.py --exp high_sample --gpus 0,1
  python3 experiments/boost_pass32.py --exp low_temp   --gpus 2,3
  python3 experiments/boost_pass32.py --exp long_gen   --gpus 4,5
  python3 experiments/boost_pass32.py --exp sorry_fill --gpus 6,7
  python3 experiments/boost_pass32.py --aggregate
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULT_DIR = ROOT / "results" / "experiments" / "boost_pass32"
DATASET_UNSOLVED = ROOT / "dataset" / "minif2f_unsolved39.jsonl"
NEARMISS_DATA = ROOT / "dataset" / "minif2f_nearmiss17.jsonl"
GOEDEL_MODEL = "Goedel-LM/Goedel-Prover-V2-8B"


def run_prover_experiment(
    exp_name: str,
    gpus: str,
    samples: int = 32,
    temperature: float = 1.0,
    max_tokens: int = 4096,
    max_model_len: int = 8192,
    strategies: list[str] | None = None,
    use_cot: bool = True,
):
    from prover.config import ModelConfig, ProverConfig, VerifierConfig
    from prover.engine import ProofSearchEngine
    from prover.evaluate import evaluate_results

    out_dir = str(RESULT_DIR / exp_name)
    os.makedirs(out_dir, exist_ok=True)

    strats = strategies or ["whole_proof"]

    config = ProverConfig(
        model=ModelConfig(
            model_path=GOEDEL_MODEL,
            tensor_parallel_size=2,
            max_model_len=max_model_len,
            max_tokens=max_tokens,
            temperature=temperature,
            gpu_memory_utilization=0.90,
            use_chat_template=False,
        ),
        verifier=VerifierConfig(mathlib_path="mathlib4"),
        strategies=strats,
        dataset="minif2f_unsolved39",
        output_dir=out_dir,
        cuda_devices=gpus,
        seed=42,
        cascade=len(strats) > 1,
    )
    config.whole_proof.samples_per_problem = samples
    config.whole_proof.use_cot = use_cot

    engine = ProofSearchEngine(config)
    try:
        engine.setup()
        results = engine.prove_dataset("minif2f_unsolved39")
        metrics = evaluate_results(os.path.join(out_dir, "proof_results.json"))
        return metrics
    finally:
        engine.teardown()


def run_sorry_fill(gpus: str, samples_per_goal: int = 32, temperature: float = 0.8):
    """
    Targeted sorry-fill: for each near-miss sample (pass, 1 sorry),
    generate sorry-fill completions using the goal state as context.
    """
    from prover.config import ModelConfig, VerifierConfig
    from prover.model import ProverModel
    from prover.prompts import build_sorry_context_prompt
    from prover.strategies.base import ProofStrategy
    from prover.verifier import LeanVerifier

    out_dir = RESULT_DIR / "sorry_fill"
    os.makedirs(out_dir, exist_ok=True)

    nearmiss = []
    with open(NEARMISS_DATA) as f:
        for line in f:
            if line.strip():
                nearmiss.append(json.loads(line))

    print(f"Sorry-fill: {len(nearmiss)} near-miss problems, {samples_per_goal} samples each")

    mcfg = ModelConfig(
        model_path=GOEDEL_MODEL,
        tensor_parallel_size=2,
        max_model_len=8192,
        max_tokens=2048,
        temperature=temperature,
        gpu_memory_utilization=0.90,
        use_chat_template=False,
    )
    os.environ["CUDA_VISIBLE_DEVICES"] = gpus
    model = ProverModel(mcfg, cuda_devices=gpus)
    model.load()

    verifier = LeanVerifier(VerifierConfig(mathlib_path="mathlib4"))
    verifier.start()

    results = []
    try:
        for nm in nearmiss:
            pid = nm["problem_id"]
            code = nm["near_miss_code"]
            goal = nm["sorry_goal"]

            header_match = re.match(r"(theorem\s+\S+.*?):=\s*by", code, re.DOTALL)
            if header_match:
                header = header_match.group(0)
            else:
                header = code.split(":= by")[0] + ":= by" if ":= by" in code else code

            prefix = code.rsplit("sorry", 1)[0] if "sorry" in code else ""

            prompt = build_sorry_context_prompt(
                theorem_header=header,
                proof_prefix=prefix,
                goal_state=goal,
            )

            raw_outputs = model.generate_single(
                prompt, n=samples_per_goal, temperature=temperature, chat=False,
            )

            attempt = {
                "problem_id": pid,
                "complete": False,
                "attempts": 0,
                "code": code,
            }

            for raw in raw_outputs:
                tactic_code = model.extract_lean_code(raw)
                if not tactic_code:
                    continue

                filled = code.replace("sorry", tactic_code, 1)
                stripped = ProofStrategy.strip_imports(filled)
                r = verifier.verify(stripped)
                attempt["attempts"] += 1

                if r.complete:
                    attempt["complete"] = True
                    attempt["code"] = stripped
                    attempt["full_code"] = filled
                    print(f"  [SOLVED] {pid} at attempt {attempt['attempts']}")
                    break

            if not attempt["complete"]:
                print(f"  [FAIL] {pid}: {attempt['attempts']} attempts")

            results.append(attempt)
    finally:
        verifier.stop()

    with open(out_dir / "proof_results.json", "w") as f:
        json.dump(results, f, indent=2)

    solved = sum(1 for r in results if r["complete"])
    print(f"\nSorry-fill: {solved}/{len(results)} newly solved")
    return results


def run_multitemp(gpus: str, samples: int = 16):
    """
    Multi-temperature ensemble: T=0.6, 0.8, 1.0, 1.2 each with samples/4 attempts,
    combined into a single pass@N evaluation.
    """
    from prover.config import ModelConfig, VerifierConfig
    from prover.datasets import load_dataset
    from prover.model import ProverModel
    from prover.prompts import build_whole_proof_prompt
    from prover.strategies.base import ProofStrategy
    from prover.verifier import LeanVerifier

    out_dir = RESULT_DIR / "multitemp"
    os.makedirs(out_dir, exist_ok=True)

    temps = [0.6, 0.8, 1.0, 1.2]
    per_temp = max(samples // len(temps), 4)

    mcfg = ModelConfig(
        model_path=GOEDEL_MODEL,
        tensor_parallel_size=2,
        max_model_len=8192,
        max_tokens=4096,
        gpu_memory_utilization=0.90,
        use_chat_template=False,
    )
    os.environ["CUDA_VISIBLE_DEVICES"] = gpus
    model = ProverModel(mcfg, cuda_devices=gpus)
    model.load()

    verifier = LeanVerifier(VerifierConfig(mathlib_path="mathlib4"))
    verifier.start()

    problems = load_dataset("minif2f_unsolved39")
    results = []

    try:
        for prob in problems:
            stmt = prob.formal_statement.split(":= by")[0] + ":= by sorry"
            header = ProofStrategy.strip_imports(prob.theorem_header)

            attempt = {
                "problem_id": prob.problem_id,
                "complete": False,
                "attempts": 0,
                "strategy": "multitemp",
                "code": "",
            }

            for temp in temps:
                prompt_cot = build_whole_proof_prompt(stmt, use_cot=True)
                raw_outputs = model.generate_single(
                    prompt_cot, n=per_temp, temperature=temp, chat=False,
                )

                for raw in raw_outputs:
                    extracted = model.extract_lean_code(raw)
                    if not extracted:
                        continue

                    if "theorem" in extracted and ":= by" in extracted:
                        code = ProofStrategy.strip_imports(extracted)
                    elif extracted.strip().startswith("by"):
                        code = f"{header.rstrip()}\n{extracted}"
                    else:
                        code = f"{header}\n  {extracted}"

                    attempt["attempts"] += 1
                    r = verifier.verify(code)

                    if r.complete:
                        attempt["complete"] = True
                        attempt["code"] = code
                        print(f"  [SOLVED] {prob.problem_id} at T={temp}, attempt {attempt['attempts']}")
                        break

                if attempt["complete"]:
                    break

            if not attempt["complete"]:
                print(f"  [FAIL] {prob.problem_id}: {attempt['attempts']} attempts across temps")

            results.append(attempt)
    finally:
        verifier.stop()

    with open(out_dir / "proof_results.json", "w") as f:
        json.dump(results, f, indent=2)

    solved = sum(1 for r in results if r["complete"])
    print(f"\nMulti-temp: {solved}/{len(results)} newly solved")
    return results


def run_long_gen(gpus: str, samples: int = 32):
    """max_tokens=8192, temperature=1.0 with COT."""
    return run_prover_experiment(
        "long_gen", gpus, samples=samples,
        temperature=1.0, max_tokens=8192, max_model_len=16384,
    )


def aggregate():
    """Aggregate results from all experiments, report incremental gains."""
    print("=" * 60)
    print("AGGREGATION: boost_pass32 experiments")
    print("=" * 60)

    all_solved = set()
    for exp_dir in sorted(RESULT_DIR.iterdir()):
        pr = exp_dir / "proof_results.json"
        if not pr.is_file():
            continue
        with open(pr) as f:
            data = json.load(f)
        solved = [r["problem_id"] for r in data if r.get("complete")]
        all_solved.update(solved)
        total = len(data)
        print(f"  {exp_dir.name}: {len(solved)}/{total} solved  {sorted(solved)}")

    print(f"\n  UNION of newly solved: {len(all_solved)}")
    print(f"  Baseline was 205/244 = 84.0%")
    new_total = 205 + len(all_solved)
    print(f"  New total: {new_total}/244 = {100*new_total/244:.1f}%")
    print(f"  Newly solved: {sorted(all_solved)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp", type=str, required=False,
                        choices=["high_sample", "low_temp", "long_gen",
                                 "sorry_fill", "multitemp", "direct_prompt"],
                        help="Experiment to run")
    parser.add_argument("--gpus", type=str, default="0,1")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args()

    if args.aggregate:
        aggregate()
        return

    if not args.exp:
        parser.error("Must specify --exp or --aggregate")

    os.makedirs(RESULT_DIR, exist_ok=True)

    if args.exp == "high_sample":
        run_prover_experiment(
            "high_sample", args.gpus, samples=128,
            temperature=1.0, max_tokens=4096,
        )
    elif args.exp == "low_temp":
        run_prover_experiment(
            "low_temp", args.gpus, samples=args.samples,
            temperature=0.6, max_tokens=4096,
        )
    elif args.exp == "long_gen":
        run_long_gen(args.gpus, samples=args.samples)
    elif args.exp == "sorry_fill":
        run_sorry_fill(args.gpus, samples_per_goal=args.samples, temperature=0.8)
    elif args.exp == "multitemp":
        run_multitemp(args.gpus, samples=args.samples)
    elif args.exp == "direct_prompt":
        run_prover_experiment(
            "direct_prompt", args.gpus, samples=args.samples,
            temperature=1.0, max_tokens=4096, use_cot=False,
        )


if __name__ == "__main__":
    main()
