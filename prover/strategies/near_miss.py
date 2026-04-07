"""
Near-miss refinement strategy.

Takes existing proofs that compile but contain sorry gaps, extracts the
remaining goals using the REPL, and generates targeted tactics to fill
them. This combines the strengths of:
- Whole-proof generation (gets the overall structure right)
- Stepwise search (uses REPL feedback for targeted gap-filling)
- Self-refinement (iteratively improves on the best attempt)

In cascade mode, this strategy also receives sorry proofs discovered
by preceding strategies (whole_proof, refinement) via set_cascade_context.
"""
import json
import os
import re
from typing import Optional

from ..prompts import (
    build_refinement_prompt,
    build_sorry_context_prompt,
    build_whole_proof_prompt,
)
from ..verifier import VerifyResult
from .base import ProofAttempt, ProofStrategy


class NearMissStrategy(ProofStrategy):
    """
    Start from existing sorry proofs (near-misses) and systematically
    try to fill the remaining gaps.

    Pipeline:
    1. Load sorry proofs from baseline results or cascade context
    2. For each sorry proof, extract precise goal state at each sorry via REPL
    3. Generate targeted tactics using context-aware prompts (proof prefix + goal state)
    4. Optionally run local stepwise search at each sorry position
    5. If gap-filling fails, generate new whole proofs informed by sorry structure
    """
    name = "near_miss"

    def __init__(self, model, verifier, config, sorry_proofs: Optional[dict] = None):
        super().__init__(model, verifier, config)
        self._sorry_proofs = sorry_proofs or {}
        self._cascade_ctx = None

    def set_cascade_context(self, ctx: dict):
        """Receive context from previous strategies in cascade mode."""
        self._cascade_ctx = ctx

    def load_baseline(self, path: str):
        """Load sorry proofs from baseline compilation results.

        Supports two formats:
        - Old pipeline: compilation_result.pass / .complete / .sorries
        - Prover framework: code with 'sorry', complete=False, no compilation_result
        """
        if not os.path.exists(path):
            print(f"  [near_miss] Baseline not found: {path}")
            return

        with open(path) as f:
            results = json.load(f)

        for r in results:
            pid = str(r.get("problem_id", ""))
            base_pid = re.sub(r"_g\d+$", "", pid)
            cr = r.get("compilation_result") or {}
            code = r.get("full_code") or r.get("code", "")

            if not cr and code and "sorry" in code and not r.get("complete", False):
                cr = {"pass": True, "complete": False, "sorries": []}

            if cr.get("pass") and not cr.get("complete") and code:
                if base_pid not in self._sorry_proofs:
                    self._sorry_proofs[base_pid] = []
                self._sorry_proofs[base_pid].append({
                    "code": code,
                    "sorries": cr.get("sorries", []),
                    "n_sorry": len(cr.get("sorries", [])) or code.count("sorry"),
                })

        for pid in self._sorry_proofs:
            self._sorry_proofs[pid].sort(key=lambda x: x["n_sorry"])

        print(f"  [near_miss] Loaded sorry proofs for {len(self._sorry_proofs)} problems")

    def prove(self, problem_id: str, formal_statement: str, theorem_header: str) -> ProofAttempt:
        cfg = self.config.near_miss
        header = self.strip_imports(theorem_header)

        attempt = ProofAttempt(
            problem_id=problem_id,
            formal_statement=formal_statement,
            strategy=self.name,
        )

        sorry_proofs = list(self._sorry_proofs.get(problem_id, []))

        if self._cascade_ctx and self._cascade_ctx.get("sorry_proofs"):
            for sp in self._cascade_ctx["sorry_proofs"]:
                sorry_proofs.append({
                    "code": sp["code"],
                    "sorries": [],
                    "n_sorry": sp.get("n_sorry", 1),
                })
            sorry_proofs.sort(key=lambda x: x["n_sorry"])

        if not sorry_proofs:
            print(f"    No sorry proofs available for {problem_id}")
            return attempt

        for sp in sorry_proofs[:3]:
            code = sp["code"]
            result = self._try_fill_sorry_context_aware(code, header, attempt, cfg.max_rounds)
            if attempt.complete:
                return attempt

        best_sorry = sorry_proofs[0]["code"]
        self._informed_generation(header, formal_statement, best_sorry, attempt)

        return attempt

    def _try_fill_sorry_context_aware(
        self, code: str, header: str, attempt: ProofAttempt, max_rounds: int,
    ) -> Optional[VerifyResult]:
        """Fill sorry gaps using context-aware prompts with precise goal states from REPL."""
        current_code = code

        for round_num in range(max_rounds):
            result = self.verifier.verify(current_code)
            attempt.attempts += 1

            if result.complete:
                attempt.complete = True
                attempt.code = current_code
                attempt.best_result = result
                attempt.all_codes.append(current_code)
                return result

            attempt.all_codes.append(current_code)
            if attempt.best_result is None or self._score(result) > self._score(attempt.best_result):
                attempt.best_result = result
                attempt.code = current_code

            if not result.success or not result.goals:
                break

            sorry_positions = self._find_sorry_positions(current_code)
            if not sorry_positions:
                break

            filled_code = self._fill_goals_with_context(
                current_code, header, result, sorry_positions,
            )
            if filled_code == current_code:
                break
            current_code = filled_code

        return attempt.best_result

    @staticmethod
    def _find_sorry_positions(code: str) -> list[dict]:
        """Find line numbers and surrounding context for each sorry in the code."""
        positions = []
        lines = code.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "sorry" or stripped.startswith("sorry ") or " sorry" in stripped:
                prefix_start = max(0, i - 5)
                prefix = "\n".join(lines[prefix_start:i])
                suffix_end = min(len(lines), i + 3)
                suffix = "\n".join(lines[i + 1:suffix_end])
                positions.append({
                    "line": i,
                    "prefix": prefix,
                    "suffix": suffix,
                    "indent": len(line) - len(line.lstrip()),
                })
        return positions

    def _fill_goals_with_context(
        self, code: str, header: str, result: VerifyResult,
        sorry_positions: list[dict],
    ) -> str:
        """Fill sorry gaps using context-aware prompts."""
        cfg = self.config.near_miss
        use_chat = self.config.model.use_chat_template
        current = code

        goals_to_fill = result.goals[:cfg.max_sorry_gaps]

        for idx, goal in enumerate(goals_to_fill):
            goal_text = goal if isinstance(goal, str) else str(goal)
            ctx = sorry_positions[idx] if idx < len(sorry_positions) else {}
            prefix = ctx.get("prefix", "")

            prompt = build_sorry_context_prompt(
                theorem_header=header,
                proof_prefix=prefix,
                goal_state=goal_text,
                full_proof=current,
            )
            raw_outputs = self.model.generate_single(
                prompt,
                n=cfg.samples_per_round,
                temperature=self.config.model.temperature,
                max_tokens=1024,
                chat=use_chat,
            )

            best_fill = None
            best_score = -999

            for raw in raw_outputs:
                extracted = self.model.extract_lean_code(raw) or self.model.extract_single_tactic(raw)
                if not extracted:
                    continue

                candidate = current.replace("sorry", extracted, 1)
                check = self.verifier.verify(candidate)

                score = self._score(check)
                if check.complete:
                    return candidate
                if score > best_score:
                    best_score = score
                    best_fill = candidate

            if best_fill and best_score > self._score_code(current):
                current = best_fill

        return current

    def _informed_generation(
        self, header: str, formal_statement: str,
        sorry_proof: str, attempt: ProofAttempt,
    ):
        """Generate new proofs informed by the structure of the best sorry proof."""
        cfg = self.config.near_miss
        use_chat = self.config.model.use_chat_template
        stmt = formal_statement.split(":= by")[0] + ":= by sorry"

        prompt = (
            f"Complete the following Lean 4 code with a formal proof.\n\n"
            f"```lean4\n{stmt}\n```\n\n"
            f"A previous attempt was close but had unproven gaps (marked with sorry):\n"
            f"```lean4\n{sorry_proof}\n```\n\n"
            f"Write a COMPLETE proof without sorry. You may use a different approach "
            f"or fix the gaps in the previous attempt."
        )

        raw_outputs = self.model.generate_single(
            prompt,
            n=cfg.samples_per_round,
            temperature=self.config.model.temperature,
            chat=use_chat,
        )

        for raw in raw_outputs:
            extracted = self.model.extract_lean_code(raw)
            if not extracted:
                continue

            code = self._assemble(header, extracted)
            attempt.attempts += 1
            attempt.all_codes.append(code)

            result = self.verifier.verify(code)
            if result.complete:
                attempt.complete = True
                attempt.code = code
                attempt.best_result = result
                return

            if attempt.best_result is None or self._score(result) > self._score(attempt.best_result):
                attempt.best_result = result
                attempt.code = code

    def _assemble(self, header: str, extracted: str) -> str:
        if "theorem" in extracted and ":= by" in extracted:
            return self.strip_imports(extracted)
        if extracted.strip().startswith("by"):
            return f"{header.rstrip()}\n{extracted}"
        return f"{header}\n  {extracted}"

    def _score_code(self, code: str) -> float:
        result = self.verifier.verify(code)
        return self._score(result)

    @staticmethod
    def _score(result: VerifyResult) -> float:
        if result.complete:
            return 100.0
        if result.success:
            return 10.0 - len(result.sorries)
        return -len(result.errors)
