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

  # Goedel-V2-32B README-aligned miniF2F baseline (official prompt + 32× n=1)
  python3 -m prover.run --dataset minif2f --split test --model Goedel-LM/Goedel-Prover-V2-32B \
    --tp 2 --gpus 4,5 --goedel-baseline --samples 32
  # Two-phase: inference JSON under output_dir/inference/, then parallel Lean (≤500GB budget by default)
  python3 -m prover.run --dataset minif2f --split test --model ... --strategies whole_proof \
    --goedel-baseline --defer-verification --verify-workers 8 --verify-memory-budget-gb 500

  # Cascade + SGE warm-start: whole_proof 中首个失败 tactic 之前的前缀 → stepwise 从该 goal 继续
  python3 -m prover.run --dataset minif2f --strategies whole_proof stepwise --cascade --limit 5

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
                        help="Dataset name (minif2f, putnambench, fate_h, fate_m, fate_x, proofnet, ...) "
                        "or path to a .jsonl/.json file (absolute paths OK).")
    parser.add_argument(
        "--dataset-dir",
        type=str,
        default=None,
        help="Override dataset/ directory for registry entries (e.g. miniF2F_v2s.jsonl under a custom folder).",
    )
    parser.add_argument("--split", type=str, default=None, help="Dataset split (valid/test)")
    parser.add_argument(
        "--problem-ids",
        type=str,
        default="",
        help="Comma-separated problem_id list (applied after --split filter).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max problems to process")
    parser.add_argument("--model", type=str, default="deepseek-ai/DeepSeek-Prover-V2-7B")
    parser.add_argument(
        "--backend",
        type=str,
        default="vllm",
        choices=("vllm", "openai_compat"),
        help="Model backend type: local vLLM or OpenAI-compatible API.",
    )
    parser.add_argument("--gpus", type=str, default="", help="CUDA_VISIBLE_DEVICES")
    parser.add_argument("--tp", type=int, default=2, help="Tensor parallel size")
    parser.add_argument("--api-base-url", type=str, default="", help="OpenAI-compatible API base URL")
    parser.add_argument(
        "--api-key-env",
        type=str,
        default="OPENAI_API_KEY",
        help="Environment variable storing API key for --backend openai_compat.",
    )
    parser.add_argument("--api-model", type=str, default="", help="API model name override")
    parser.add_argument("--api-timeout-s", type=int, default=120, help="API request timeout in seconds")
    parser.add_argument("--api-max-retries", type=int, default=4, help="API retries on 429/5xx")
    parser.add_argument("--strategies", nargs="+", default=["whole_proof", "stepwise", "refinement"])
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--samples", type=int, default=32, help="Samples per problem (whole_proof)")
    parser.add_argument("--draft-samples", type=int, default=2, help="Natural-language draft samples (draft_formalize)")
    parser.add_argument("--formalize-samples", type=int, default=4, help="Lean samples per draft (draft_formalize)")
    parser.add_argument("--draft-rounds", type=int, default=2, help="Max revise rounds (draft_formalize)")
    parser.add_argument(
        "--draft-repair-steps",
        type=int,
        default=2,
        help="Per-candidate Lean-feedback repair steps (draft_formalize).",
    )
    parser.add_argument(
        "--draft-sorry-candidates",
        type=int,
        default=3,
        help="Candidates per sorry-goal repair step (draft_formalize).",
    )
    parser.add_argument(
        "--draft-feedback-chars",
        type=int,
        default=1500,
        help="Max Lean feedback chars injected into draft revision prompts.",
    )
    parser.add_argument(
        "--no-error-sorry-decompose",
        action="store_true",
        help="Disable error-line->sorry subgoal decomposition in draft_formalize.",
    )
    parser.add_argument(
        "--no-localized-repair-feedback",
        action="store_true",
        help="Disable localized line-aware repair feedback in draft_formalize.",
    )
    parser.add_argument(
        "--draft-enable-sketch-first",
        action="store_true",
        help="Enable sketch-first branch (NL draft -> lemma-style Lean sketch) in draft_formalize.",
    )
    parser.add_argument(
        "--draft-sketch-samples",
        type=int,
        default=2,
        help="Sketch candidates per draft for sketch-first branch (draft_formalize).",
    )
    parser.add_argument(
        "--draft-min-sketch-lemmas",
        type=int,
        default=3,
        help="Minimum intermediate lemma count encouraged in sketch-first prompts.",
    )
    parser.add_argument(
        "--no-draft-global-gap-feedback",
        action="store_true",
        help="Disable global proof-gap feedback in draft revision prompts.",
    )
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--no-chat", action="store_true",
                        help="Disable chat template. Goedel-Prover-V2 (Qwen3) is trained with chat—leave this off for official-style eval.")
    parser.add_argument("--stepwise-depth", type=int, default=15)
    parser.add_argument("--stepwise-width", type=int, default=8)
    parser.add_argument("--stepwise-budget", type=int, default=200, help="Max nodes in stepwise search")
    parser.add_argument("--no-api-json-tactic", action="store_true",
                        help="Disable API stepwise JSON tactic output constraint.")
    parser.add_argument("--no-typed-action-masking", action="store_true",
                        help="Disable error-type aware action filtering in stepwise.")
    parser.add_argument("--no-progress-value", action="store_true",
                        help="Disable learned progress value function in priority ranking.")
    parser.add_argument("--value-weights", type=str, default="",
                        help="Path to offline-fitted value function weights JSON.")
    parser.add_argument("--priority-alpha", type=float, default=1.0,
                        help="Heuristic weight in stepwise priority.")
    parser.add_argument("--priority-beta", type=float, default=40.0,
                        help="Value-function weight in stepwise priority.")
    parser.add_argument("--refinement-rounds", type=int, default=3)
    parser.add_argument("--near-miss-rounds", type=int, default=5)
    parser.add_argument("--near-miss-samples", type=int, default=8)
    parser.add_argument("--baseline-results", type=str, default="",
                        help="Path to compilation results for near-miss baseline")
    parser.add_argument("--cascade", action="store_true",
                        help="Enable strategy cascade: pass intermediate results between strategies")
    parser.add_argument(
        "--no-warm-start-stepwise",
        action="store_true",
        help="Disable whole→stepwise warm-start (failed tactic → prefix+sorry goal for SGE).",
    )
    parser.add_argument(
        "--no-prior-failure-hints",
        action="store_true",
        help="Cascade stepwise: do not inject prior whole-proof failing tactic + REPL errors into prompts.",
    )
    parser.add_argument("--shard-id", type=int, default=0, help="Shard index for parallel runs")
    parser.add_argument("--num-shards", type=int, default=1, help="Total number of shards")
    parser.add_argument("--resume", type=str, default=None, help="Resume from previous results file")
    parser.add_argument("--evaluate", type=str, default=None, help="Only evaluate existing results")
    parser.add_argument("--mathlib-path", type=str, default="mathlib4")
    parser.add_argument(
        "--verifier-timeout",
        type=int,
        default=None,
        help="Lean REPL 单次 verify 超时（秒）。未指定时：--goedel-baseline 为 600，否则 120。",
    )
    parser.add_argument("--gpu-mem-util", type=float, default=0.85)
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子；传入 vLLM LLM(seed=…)。官方 README Quick Start 示例使用 30。",
    )
    parser.add_argument(
        "--goedel-baseline",
        action="store_true",
        help="Align with Goedel-Prover-V2 README: whole_proof + official prompt + independent n=1 samples; "
        "raises max-tokens/max-model-len/gpu-mem when left at defaults.",
    )
    parser.add_argument(
        "--independent-samples",
        action="store_true",
        help="whole_proof: run samples_per_problem separate n=1 generations (Pass@K protocol).",
    )
    parser.add_argument(
        "--batch-samples",
        action="store_true",
        help="whole_proof: single request with n=samples (default unless --goedel-baseline / --independent-samples).",
    )
    parser.add_argument(
        "--whole-proof-prompt",
        type=str,
        default=None,
        choices=("cot", "direct", "goedel_v2_official"),
        help="Override whole_proof prompt style (default: cot; --goedel-baseline sets goedel_v2_official).",
    )
    parser.add_argument(
        "--defer-verification",
        action="store_true",
        help="whole_proof only: run all LLM samples first, write output_dir/inference/*.json, "
        "then verify in parallel worker processes (see --verify-*).",
    )
    parser.add_argument(
        "--verify-workers",
        type=int,
        default=8,
        help="Max parallel Lean verify processes when --defer-verification (also capped by memory).",
    )
    parser.add_argument(
        "--verify-memory-budget-gb",
        type=float,
        default=500.0,
        help="Rough RAM budget (GB) for parallel Lean workers during deferred verification.",
    )
    parser.add_argument(
        "--verify-memory-per-job-gb",
        type=float,
        default=4.0,
        help="Heuristic GB per Lean worker for concurrency cap (budget / per_job).",
    )

    args = parser.parse_args()

    verifier_timeout = args.verifier_timeout
    if verifier_timeout is None:
        verifier_timeout = 600 if args.goedel_baseline else 120
    verifier_import_timeout = max(180, verifier_timeout)

    if args.defer_verification and args.strategies != ["whole_proof"]:
        parser.error("--defer-verification 仅能与 --strategies whole_proof 联用（不要加其它策略）")

    if args.evaluate:
        metrics = evaluate_results(args.evaluate)
        print_report(metrics, dataset_name=os.path.basename(os.path.dirname(args.evaluate)))
        return

    problem_ids = None
    if args.problem_ids.strip():
        problem_ids = [x.strip() for x in args.problem_ids.split(",") if x.strip()]

    output_dir = args.output_dir or f"results/prover/{args.dataset}"

    if args.goedel_baseline:
        # 对齐 Goedel-Prover-V2 inference.py：max_tokens 与 max_model_len 同阶（pipeline 默认 40960）
        if args.max_tokens == 4096:
            args.max_tokens = 40960
        if args.max_model_len == 8192:
            args.max_model_len = 40960
        if args.gpu_mem_util == 0.85:
            args.gpu_mem_util = 0.9
        # cascade（如 whole→stepwise repair）需保留用户指定的 strategies
        if not args.cascade:
            args.strategies = ["whole_proof"]

    config = ProverConfig(
        model=ModelConfig(
            model_path=args.model,
            backend_type=args.backend,
            tensor_parallel_size=args.tp,
            max_model_len=args.max_model_len,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            gpu_memory_utilization=args.gpu_mem_util,
            use_chat_template=not args.no_chat,
            seed=args.seed,
            api_base_url=args.api_base_url,
            api_key=os.environ.get(args.api_key_env, ""),
            api_model=args.api_model,
            api_timeout_s=args.api_timeout_s,
            api_max_retries=args.api_max_retries,
        ),
        verifier=VerifierConfig(
            mathlib_path=args.mathlib_path,
            timeout=verifier_timeout,
            import_timeout=verifier_import_timeout,
        ),
        strategies=args.strategies,
        dataset=args.dataset,
        dataset_dir=args.dataset_dir,
        output_dir=output_dir,
        cuda_devices=args.gpus,
        seed=args.seed,
        cascade=args.cascade,
        warm_start_stepwise_from_whole=not args.no_warm_start_stepwise,
        defer_verification=args.defer_verification,
        verify_workers=args.verify_workers,
        verify_memory_budget_gb=args.verify_memory_budget_gb,
        verify_memory_per_job_gb=args.verify_memory_per_job_gb,
    )
    config.whole_proof.samples_per_problem = args.samples
    config.draft_formalize.draft_samples = args.draft_samples
    config.draft_formalize.formalize_samples = args.formalize_samples
    config.draft_formalize.max_rounds = args.draft_rounds
    config.draft_formalize.max_feedback_chars = args.draft_feedback_chars
    config.draft_formalize.code_repair_steps = args.draft_repair_steps
    config.draft_formalize.sorry_fill_candidates = args.draft_sorry_candidates
    config.draft_formalize.enable_error_sorry_decompose = not args.no_error_sorry_decompose
    config.draft_formalize.enable_localized_feedback = not args.no_localized_repair_feedback
    config.draft_formalize.enable_sketch_first = args.draft_enable_sketch_first
    config.draft_formalize.sketch_samples = args.draft_sketch_samples
    config.draft_formalize.min_sketch_lemmas = args.draft_min_sketch_lemmas
    config.draft_formalize.enable_global_gap_feedback = not args.no_draft_global_gap_feedback
    if args.whole_proof_prompt:
        config.whole_proof.prompt_style = args.whole_proof_prompt
    elif args.goedel_baseline:
        config.whole_proof.prompt_style = "goedel_v2_official"
    if args.batch_samples:
        config.whole_proof.independent_samples = False
    elif args.independent_samples or args.goedel_baseline:
        config.whole_proof.independent_samples = True
    config.stepwise.max_depth = args.stepwise_depth
    config.stepwise.max_width = args.stepwise_width
    config.stepwise.max_total_nodes = args.stepwise_budget
    config.stepwise.api_json_tactic_mode = not args.no_api_json_tactic
    config.stepwise.enable_typed_action_masking = not args.no_typed_action_masking
    config.stepwise.use_progress_value_function = not args.no_progress_value
    config.stepwise.value_function_weights_path = args.value_weights
    config.stepwise.priority_alpha = args.priority_alpha
    config.stepwise.priority_beta = args.priority_beta
    if args.no_prior_failure_hints:
        config.stepwise.inject_prior_failure_hints = False
    config.refinement.max_rounds = args.refinement_rounds
    config.near_miss.max_rounds = args.near_miss_rounds
    config.near_miss.samples_per_round = args.near_miss_samples
    config.near_miss.baseline_results_path = args.baseline_results

    engine = ProofSearchEngine(config)

    try:
        engine.setup()
        results = engine.prove_dataset(
            args.dataset,
            split=args.split,
            limit=args.limit,
            resume_from=args.resume,
            shard_id=args.shard_id,
            num_shards=args.num_shards,
            problem_ids=problem_ids,
        )
        metrics = evaluate_results(os.path.join(output_dir, "proof_results.json"))
        print_report(metrics, dataset_name=args.dataset)
    finally:
        engine.teardown()


if __name__ == "__main__":
    main()
