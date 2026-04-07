"""
Main proof search engine.
Orchestrates multiple strategies, manages budget, collects results.

When cascade mode is enabled, intermediate results (best sorry proofs,
error patterns) are passed between strategies so each can build on the
previous one's progress.
"""
import json
import os
import time
from dataclasses import asdict
from typing import Optional

from .config import ProverConfig
from .datasets import Problem, load_dataset
from .model import ProverModel
from .strategies import STRATEGY_REGISTRY, ProofAttempt
from .verifier import LeanVerifier


class ProofSearchEngine:
    """
    Unified proof search engine.

    For each problem, runs configured strategies in order until
    a complete proof is found or budget is exhausted.

    In cascade mode, each strategy receives context from previous
    strategies (best sorry proofs, error patterns) to build upon.
    """

    def __init__(self, config: Optional[ProverConfig] = None):
        self.config = config or ProverConfig()
        self.model = ProverModel(self.config.model, self.config.cuda_devices)
        self.verifier = LeanVerifier(self.config.verifier)
        self.strategies = []
        self.results: list[ProofAttempt] = []

    def setup(self):
        """Load model and start verifier."""
        print(f"Loading model: {self.config.model.model_path}")
        self.model.load()
        print("Starting Lean verifier...")
        self.verifier.start()

        for name in self.config.strategies:
            if name not in STRATEGY_REGISTRY:
                print(f"Warning: unknown strategy '{name}', skipping")
                continue
            strategy_cls = STRATEGY_REGISTRY[name]
            strategy = strategy_cls(self.model, self.verifier, self.config)

            if name == "near_miss" and self.config.near_miss.baseline_results_path:
                strategy.load_baseline(self.config.near_miss.baseline_results_path)

            self.strategies.append(strategy)
            print(f"  Strategy registered: {name}")

        if self.config.cascade:
            print("  Cascade mode: ON (strategies share intermediate results)")

    def teardown(self):
        self.verifier.stop()

    def prove_one(self, problem: Problem) -> ProofAttempt:
        """Try to prove a single problem using all strategies in order."""
        best_attempt = None
        cascade_ctx = {} if self.config.cascade else None

        for strategy in self.strategies:
            print(f"  [{strategy.name}] Attempting {problem.problem_id}...")
            t0 = time.time()

            try:
                if cascade_ctx is not None and hasattr(strategy, 'set_cascade_context'):
                    strategy.set_cascade_context(cascade_ctx)

                attempt = strategy.prove(
                    problem_id=problem.problem_id,
                    formal_statement=problem.lean4_code,
                    theorem_header=problem.theorem_header,
                )
            except Exception as e:
                print(f"  [{strategy.name}] Error: {e}")
                continue

            elapsed = time.time() - t0
            attempt.metadata["strategy_time"] = round(elapsed, 2)

            if cascade_ctx is not None:
                self._update_cascade_context(cascade_ctx, attempt)

            if attempt.complete:
                print(f"  [{strategy.name}] SOLVED in {elapsed:.1f}s ({attempt.attempts} attempts)")
                return attempt

            if best_attempt is None or self._compare(attempt, best_attempt) > 0:
                best_attempt = attempt

            print(f"  [{strategy.name}] Not solved ({attempt.attempts} attempts, {elapsed:.1f}s)")

        return best_attempt or ProofAttempt(
            problem_id=problem.problem_id,
            formal_statement=problem.lean4_code,
        )

    @staticmethod
    def _update_cascade_context(ctx: dict, attempt: ProofAttempt):
        """Collect useful intermediate results for the next strategy."""
        if attempt.best_result and attempt.best_result.success and not attempt.complete:
            existing = ctx.get("sorry_proofs", [])
            if attempt.code:
                existing.append({
                    "code": attempt.code,
                    "strategy": attempt.strategy,
                    "n_sorry": len(attempt.best_result.sorries) if attempt.best_result.sorries else 0,
                })
                existing.sort(key=lambda x: x["n_sorry"])
            ctx["sorry_proofs"] = existing

        if attempt.best_result and attempt.best_result.errors:
            ctx.setdefault("error_patterns", []).extend(
                e.get("data", "") for e in attempt.best_result.errors[:3]
            )

        for code in attempt.all_codes:
            ctx.setdefault("all_attempts", []).append(code)

    def prove_dataset(
        self, dataset_name: str,
        split: Optional[str] = None,
        limit: Optional[int] = None,
        resume_from: Optional[str] = None,
        shard_id: int = 0,
        num_shards: int = 1,
    ) -> list[ProofAttempt]:
        """
        Run proof search on an entire dataset.
        Results are saved incrementally.
        """
        problems = load_dataset(dataset_name, split=split, limit=limit,
                                shard_id=shard_id, num_shards=num_shards)
        shard_info = f", shard {shard_id}/{num_shards}" if num_shards > 1 else ""
        print(f"\nDataset: {dataset_name} ({len(problems)} problems{shard_info})")

        already_attempted = set()
        already_solved = set()
        if resume_from and os.path.exists(resume_from):
            with open(resume_from) as f:
                prev = json.load(f)
            for r in prev:
                self.results.append(self._dict_to_attempt(r))
                already_attempted.add(r["problem_id"])
                if r.get("complete"):
                    already_solved.add(r["problem_id"])
            print(f"  Resuming: {len(already_solved)} solved, {len(already_attempted)} attempted (skipping all)")

        solved, total = len(already_solved), len(problems)

        for i, problem in enumerate(problems):
            if problem.problem_id in already_attempted:
                continue

            print(f"\n[{i+1}/{total}] {problem.problem_id}")
            attempt = self.prove_one(problem)
            self.results.append(attempt)

            if attempt.complete:
                solved += 1
            print(f"  Progress: {solved}/{total} solved ({100*solved/total:.1f}%)")

            self._save_results()

        return self.results

    def _save_results(self):
        os.makedirs(self.config.output_dir, exist_ok=True)
        path = os.path.join(self.config.output_dir, "proof_results.json")
        serializable = []
        for r in self.results:
            d = {
                "problem_id": r.problem_id,
                "complete": r.complete,
                "strategy": r.strategy,
                "attempts": r.attempts,
                "code": r.code,
                "full_code": r.code,
                "compilation_result": {
                    "pass": (r.best_result.success if r.best_result else False),
                    "complete": r.complete,
                    "sorries": (r.best_result.sorries if r.best_result and r.best_result.sorries else []),
                    "errors": (r.best_result.errors if r.best_result and r.best_result.errors else []),
                },
                "metadata": r.metadata,
            }
            serializable.append(d)
        with open(path, "w") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _compare(a: ProofAttempt, b: ProofAttempt) -> int:
        if a.complete and not b.complete:
            return 1
        if not a.complete and b.complete:
            return -1
        sa = a.best_result and (10 if a.best_result.success else -len(a.best_result.errors)) or -999
        sb = b.best_result and (10 if b.best_result.success else -len(b.best_result.errors)) or -999
        return 1 if sa > sb else (-1 if sa < sb else 0)

    @staticmethod
    def _dict_to_attempt(d: dict) -> ProofAttempt:
        return ProofAttempt(
            problem_id=d.get("problem_id", ""),
            complete=d.get("complete", False),
            strategy=d.get("strategy", ""),
            attempts=d.get("attempts", 0),
            code=d.get("code", ""),
            metadata=d.get("metadata", {}),
        )
