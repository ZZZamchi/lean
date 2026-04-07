"""
Whole-proof generation strategy (baseline).
Generates the entire proof at once, verifies, returns best.
"""
from ..prompts import build_whole_proof_prompt
from ..verifier import VerifyResult
from .base import ProofAttempt, ProofStrategy


class WholeProofStrategy(ProofStrategy):
    name = "whole_proof"

    def prove(self, problem_id: str, formal_statement: str, theorem_header: str) -> ProofAttempt:
        cfg = self.config.whole_proof
        header = self.strip_imports(theorem_header)

        stmt = formal_statement.split(":= by")[0] + ":= by sorry"
        prompt = build_whole_proof_prompt(
            formal_statement=stmt,
            use_cot=cfg.use_cot,
        )
        use_chat = self.config.model.use_chat_template
        raw_outputs = self.model.generate_single(
            prompt,
            n=cfg.samples_per_problem,
            temperature=self.config.model.temperature,
            chat=use_chat,
        )

        attempt = ProofAttempt(
            problem_id=problem_id,
            formal_statement=formal_statement,
            strategy=self.name,
        )

        for raw in raw_outputs:
            extracted = self.model.extract_lean_code(raw)
            if not extracted:
                continue

            code = self._assemble_proof(header, extracted)
            attempt.all_codes.append(code)
            attempt.attempts += 1

            result = self.verifier.verify(code)
            if result.complete:
                attempt.complete = True
                attempt.code = code
                attempt.best_result = result
                return attempt

            if attempt.best_result is None or self._score(result) > self._score(attempt.best_result):
                attempt.best_result = result
                attempt.code = code

        return attempt

    def _assemble_proof(self, header: str, extracted: str) -> str:
        """Combine theorem header with extracted proof body."""
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
