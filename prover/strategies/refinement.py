"""
Structured self-refinement strategy with error classification.

Unlike naive correction rounds (just appending error messages),
this strategy:
1. Identifies the EXACT point of failure
2. Classifies errors (type_mismatch, unknown_identifier, tactic_failed)
3. Generates targeted fixes with error-specific guidance
4. Extracts goal state at sorry points for precise gap-filling
"""
from ..prompts import (
    build_error_typed_prompt,
    build_refinement_prompt,
    build_whole_proof_prompt,
    classify_error,
)
from ..verifier import VerifyResult
from .base import ProofAttempt, ProofStrategy


class RefinementStrategy(ProofStrategy):
    """
    Self-refinement: generate initial proof, analyze failures,
    iteratively fix the broken parts with error-aware prompts.
    """
    name = "refinement"

    def __init__(self, model, verifier, config):
        super().__init__(model, verifier, config)
        self._cascade_ctx = None

    def set_cascade_context(self, ctx: dict):
        self._cascade_ctx = ctx

    def prove(self, problem_id: str, formal_statement: str, theorem_header: str) -> ProofAttempt:
        cfg = self.config.refinement
        header = self.strip_imports(theorem_header)

        attempt = ProofAttempt(
            problem_id=problem_id,
            formal_statement=formal_statement,
            strategy=self.name,
        )

        candidates = self._generate_initial(formal_statement, header)

        for round_num in range(cfg.max_rounds):
            for code in candidates:
                attempt.attempts += 1
                result = self.verifier.verify(code)

                if result.complete:
                    attempt.complete = True
                    attempt.code = code
                    attempt.best_result = result
                    attempt.all_codes.append(code)
                    return attempt

                attempt.all_codes.append(code)
                if attempt.best_result is None or self._score(result) > self._score(attempt.best_result):
                    attempt.best_result = result
                    attempt.code = code

            if attempt.best_result is None:
                break

            candidates = self._refine(
                header, formal_statement, attempt.code, attempt.best_result, round_num
            )

        return attempt

    def _generate_initial(self, formal_statement: str, header: str) -> list[str]:
        """Generate initial proof candidates."""
        cfg = self.config.refinement
        prompt = build_whole_proof_prompt(formal_statement=formal_statement)
        use_chat = self.config.model.use_chat_template
        raw_outputs = self.model.generate_single(
            prompt,
            n=cfg.samples_per_round,
            temperature=self.config.model.temperature,
            chat=use_chat,
        )
        codes = []
        for raw in raw_outputs:
            extracted = self.model.extract_lean_code(raw)
            if extracted:
                code = self._assemble(header, extracted)
                codes.append(code)
        return codes

    def _refine(
        self, header: str, formal_statement: str,
        best_code: str, best_result: VerifyResult, round_num: int
    ) -> list[str]:
        """Generate refined candidates based on the best attempt so far."""
        if best_result.success and best_result.goals:
            return self._refine_sorry_gaps(header, best_code, best_result)

        if best_result.errors:
            return self._refine_errors_typed(header, formal_statement, best_code, best_result)

        return []

    def _refine_sorry_gaps(
        self, header: str, best_code: str, best_result: VerifyResult
    ) -> list[str]:
        """Fill sorry gaps with targeted tactics."""
        cfg = self.config.refinement
        use_chat = self.config.model.use_chat_template
        results = []

        for goal in best_result.goals[:3]:
            prompt = build_refinement_prompt(
                partial_proof=best_code,
                remaining_goal=goal,
            )
            raw_outputs = self.model.generate_single(
                prompt,
                n=cfg.samples_per_round // 2 + 1,
                temperature=self.config.model.temperature,
                max_tokens=1024,
                chat=use_chat,
            )
            for raw in raw_outputs:
                extracted = self.model.extract_lean_code(raw) or self.model.extract_single_tactic(raw)
                if extracted:
                    filled = best_code.replace("sorry", extracted, 1)
                    results.append(filled)

        return results

    def _refine_errors_typed(
        self, header: str, formal_statement: str,
        best_code: str, best_result: VerifyResult
    ) -> list[str]:
        """
        Classify errors and generate targeted fixes with error-specific guidance.
        Groups errors by category and generates fixes for each.
        """
        cfg = self.config.refinement
        use_chat = self.config.model.use_chat_template
        codes = []

        first_error = best_result.errors[0] if best_result.errors else {}
        error_data = first_error.get("data", "")
        category = classify_error(error_data)
        pos = first_error.get("pos", {})
        line = str(pos.get("line", "?"))

        all_error_msgs = []
        for e in best_result.errors[:5]:
            epos = e.get("pos", {})
            eline = epos.get("line", "?")
            ecol = epos.get("column", "?")
            edata = e.get("data", "")
            all_error_msgs.append(f"Line {eline}, Col {ecol}: {edata}")
        error_text = "\n".join(all_error_msgs)

        prompt = build_error_typed_prompt(
            failed_code=best_code,
            error_message=error_text,
            error_line=line,
            error_category=category,
        )
        raw_outputs = self.model.generate_single(
            prompt,
            n=cfg.samples_per_round,
            temperature=self.config.model.temperature,
            chat=use_chat,
        )
        for raw in raw_outputs:
            extracted = self.model.extract_lean_code(raw)
            if extracted:
                code = self._assemble(header, extracted)
                codes.append(code)

        if category != "other":
            fallback_prompt = build_refinement_prompt(
                failed_code=best_code,
                error_message=error_text,
            )
            fallback_outputs = self.model.generate_single(
                fallback_prompt,
                n=max(2, cfg.samples_per_round // 2),
                temperature=self.config.model.temperature,
                chat=use_chat,
            )
            for raw in fallback_outputs:
                extracted = self.model.extract_lean_code(raw)
                if extracted:
                    codes.append(self._assemble(header, extracted))

        return codes

    def _assemble(self, header: str, extracted: str) -> str:
        if "theorem" in extracted and ":= by" in extracted:
            return self.strip_imports(extracted)
        if extracted.strip().startswith("by"):
            return f"{header.rstrip()}\n{extracted}"
        return f"{header}\n  {extracted}"

    @staticmethod
    def _score(result: VerifyResult) -> float:
        if result.complete:
            return 100.0
        if result.success:
            return 10.0 - len(result.sorries)
        return -len(result.errors)
