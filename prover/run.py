#!/usr/bin/env python3
"""
CLI entry point for the proof search framework.

Usage examples:
  # Run on miniF2F valid split with default settings
  python -m prover.run --dataset minif2f --split valid --limit 10

  # Run stepwise-only on FATE-H
  python -m prover.run --dataset fate_h --strategies stepwise

  # Run all strategies on Putnam
  python -m prover.run --dataset putnambench --strategies whole_proof stepwise refinement

  # Goedel-V2-32B: enable chat + high token ceiling (see repo docs/GOEDEL_V2_EVALUATION.md)
  python -m prover.run --dataset minif2f --split valid \
    --model Goedel-LM/Goedel-Prover-V2-32B --tp 2 --gpus 4,5 \
    --strategies whole_proof --samples 32 --max-tokens 32768 --max-model-len 40960

  # Run strategy cascade (whole→refinement→near_miss→stepwise)
  python -m prover.run --dataset minif2f --strategies whole_proof refinement near_miss stepwise --cascade

  # Near-miss with baseline sorry proofs
  python -m prover.run --dataset minif2f --strategies near_miss --baseline-results path/to/compilation.json

  # Evaluate existing results
  python -m prover.run --evaluate results/prover/proof_results.json
"""
import argparse
import json
import os
import sys

from .config import ModelConfig, ProverConfig, VerifierConfig
from .engine import ProofSearchEngine
from .evaluate import evaluate_results, print_report


def main():
    parser = argparse.ArgumentParser(description="General-purpose Lean 4 proof search")
    parser.add_argument("--dataset", type=str, default="minif2f",
                        help="Dataset name (minif2f, putnambench, fate_h, fate_m, fate_x, proofnet, ...)")
    parser.add_argument("--split", type=str, default=None, help="Dataset split (valid/test)")
    parser.add_argument("--limit", type=int, default=None, help="Max problems to process")
    parser.add_argument("--model", type=str, default="deepseek-ai/DeepSeek-Prover-V2-7B")
    parser.add_argument("--gpus", type=str, default="", help="CUDA_VISIBLE_DEVICES")
    parser.add_argument("--tp", type=int, default=2, help="Tensor parallel size")
    parser.add_argument("--strategies", nargs="+", default=["whole_proof", "stepwise", "refinement"])
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--samples", type=int, default=32, help="Samples per problem (whole_proof)")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--no-chat", action="store_true",
                        help="Disable chat template. Goedel-Prover-V2 (Qwen3) is trained with chat—leave this off for official-style eval.")
    parser.add_argument("--stepwise-depth", type=int, default=15)
    parser.add_argument("--stepwise-width", type=int, default=8)
    parser.add_argument("--stepwise-budget", type=int, default=200, help="Max nodes in stepwise search")
    parser.add_argument("--refinement-rounds", type=int, default=3)
    parser.add_argument("--near-miss-rounds", type=int, default=5)
    parser.add_argument("--near-miss-samples", type=int, default=8)
    parser.add_argument("--baseline-results", type=str, default="",
                        help="Path to compilation results for near-miss baseline")
    parser.add_argument("--cascade", action="store_true",
                        help="Enable strategy cascade: pass intermediate results between strategies")
    parser.add_argument("--shard-id", type=int, default=0, help="Shard index for parallel runs")
    parser.add_argument("--num-shards", type=int, default=1, help="Total number of shards")
    parser.add_argument("--resume", type=str, default=None, help="Resume from previous results file")
    parser.add_argument("--evaluate", type=str, default=None, help="Only evaluate existing results")
    parser.add_argument("--mathlib-path", type=str, default="mathlib4")
    parser.add_argument("--gpu-mem-util", type=float, default=0.85)
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    if args.evaluate:
        metrics = evaluate_results(args.evaluate)
        print_report(metrics, dataset_name=os.path.basename(os.path.dirname(args.evaluate)))
        return

    output_dir = args.output_dir or f"results/prover/{args.dataset}"

    config = ProverConfig(
        model=ModelConfig(
            model_path=args.model,
            tensor_parallel_size=args.tp,
            max_model_len=args.max_model_len,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            gpu_memory_utilization=args.gpu_mem_util,
            use_chat_template=not args.no_chat,
        ),
        verifier=VerifierConfig(mathlib_path=args.mathlib_path),
        strategies=args.strategies,
        dataset=args.dataset,
        output_dir=output_dir,
        cuda_devices=args.gpus,
        seed=args.seed,
        cascade=args.cascade,
    )
    config.whole_proof.samples_per_problem = args.samples
    config.stepwise.max_depth = args.stepwise_depth
    config.stepwise.max_width = args.stepwise_width
    config.stepwise.max_total_nodes = args.stepwise_budget
    config.refinement.max_rounds = args.refinement_rounds
    config.near_miss.max_rounds = args.near_miss_rounds
    config.near_miss.samples_per_round = args.near_miss_samples
    config.near_miss.baseline_results_path = args.baseline_results

    engine = ProofSearchEngine(config)

    try:
        engine.setup()
        results = engine.prove_dataset(
            args.dataset, split=args.split, limit=args.limit, resume_from=args.resume,
            shard_id=args.shard_id, num_shards=args.num_shards,
        )
        metrics = evaluate_results(os.path.join(output_dir, "proof_results.json"))
        print_report(metrics, dataset_name=args.dataset)
    finally:
        engine.teardown()


if __name__ == "__main__":
    main()
