"""
Two-stage API-oriented strategy:
1) Generate natural-language proof drafts
2) Formalize drafts into Lean code
3) Feed Lean errors/goals back to revise drafts, then retry
"""
from __future__ import annotations

from ..prompts import (
    build_code_repair_prompt,
    build_final_mile_tactic_prompt,
    build_formalize_from_draft_prompt,
    build_nl_draft_prompt,
    build_revise_draft_prompt,
    build_sketch_from_draft_prompt,
    build_sorry_isolated_prompt,
    build_sorry_context_prompt,
)
from ..verifier import VerifyResult
from .base import ProofAttempt, ProofStrategy


class DraftFormalizeStrategy(ProofStrategy):
    name = "draft_formalize"

    def prove(self, problem_id: str, formal_statement: str, theorem_header: str) -> ProofAttempt:
        cfg = self.config.draft_formalize
        use_chat = self.config.model.use_chat_template
        header = self.strip_imports(theorem_header)
        stmt = formal_statement.split(":= by")[0] + ":= by sorry"

        attempt = ProofAttempt(
            problem_id=problem_id,
            formal_statement=formal_statement,
            strategy=self.name,
        )

        draft_prompt = build_nl_draft_prompt(stmt)
        draft_texts = self.model.generate_single(
            draft_prompt,
            n=max(1, int(cfg.draft_samples)),
            temperature=self.config.model.temperature,
            max_tokens=min(2048, self.config.model.max_tokens),
            chat=use_chat,
        )
        draft_texts = self._dedup_nonempty(draft_texts)
        if not draft_texts:
            attempt.metadata["error"] = "No natural-language draft generated"
            return attempt

        if self.tracer:
            self.tracer.log(
                "draft_generated",
                {
                    "problem_id": problem_id,
                    "strategy": self.name,
                    "n_drafts": len(draft_texts),
                },
            )

        best_result: VerifyResult | None = None
        best_code = ""
        rounds = max(1, int(cfg.max_rounds))
        for round_idx in range(rounds):
            revised_drafts: list[str] = []
            for draft_idx, draft in enumerate(draft_texts):
                prompt = build_formalize_from_draft_prompt(stmt, draft)
                raw_outputs = self.model.generate_single(
                    prompt,
                    n=max(1, int(cfg.formalize_samples)),
                    temperature=self.config.model.temperature,
                    chat=use_chat,
                )
                if bool(getattr(cfg, "enable_sketch_first", False)):
                    sketch_prompt = build_sketch_from_draft_prompt(
                        stmt,
                        draft,
                        min_lemmas=int(getattr(cfg, "min_sketch_lemmas", 3)),
                    )
                    sketch_outputs = self.model.generate_single(
                        sketch_prompt,
                        n=max(1, int(getattr(cfg, "sketch_samples", 2))),
                        temperature=max(0.0, min(0.35, float(self.config.model.temperature))),
                        chat=use_chat,
                    )
                    if sketch_outputs:
                        raw_outputs.extend(sketch_outputs)

                best_feedback_for_draft = ""
                for sample_idx, raw in enumerate(raw_outputs):
                    extracted = self.model.extract_lean_code(raw)
                    if not extracted:
                        continue
                    code = self._assemble_proof(header, extracted)
                    code = self._sanitize_code_text(code)
                    code = self._normalize_tactic_block_layout(code)
                    if self._has_invalid_nonlean_markers(code):
                        code = self._strip_nonlean_artifacts(code)
                    if self._has_hard_placeholder(code):
                        repaired = self._repair_placeholder_code(
                            formal_statement=stmt,
                            partial_code=code,
                        )
                        if repaired:
                            code = self._sanitize_code_text(repaired)
                            code = self._normalize_tactic_block_layout(code)
                    attempt.attempts += 1
                    attempt.all_codes.append(code)
                    placeholder_hit = (
                        self._has_hard_placeholder(code)
                        or self._is_trivial_sorry_skeleton(code)
                        or self._is_sorry_collapse_pattern(code)
                    )
                    if placeholder_hit:
                        # Keep a synthetic failed result so this sample can drive revision.
                        result = VerifyResult(
                            success=False,
                            complete=False,
                            errors=[{"severity": "error", "data": "placeholder_or_hole_detected"}],
                            sorries=[],
                            goals=[],
                            code=code,
                        )
                    else:
                        result = self.verifier.verify(code)
                        if bool(getattr(cfg, "enable_error_sorry_decompose", True)):
                            code, result, decompose_used = self._error_guided_sorry_decompose(
                                formal_statement=stmt,
                                theorem_header=header,
                                code=code,
                                result=result,
                                max_steps=max(0, int(getattr(cfg, "code_repair_steps", 0))),
                                candidates=max(1, int(getattr(cfg, "sorry_fill_candidates", 3))),
                            )
                            if decompose_used > 0:
                                attempt.attempts += decompose_used
                                attempt.all_codes.append(code)
                        if self._needs_parse_repair(result):
                            parse_repaired = self._repair_parse_error_code(
                                formal_statement=stmt,
                                broken_code=code,
                                error_message=self._first_error_message(result),
                            )
                            if parse_repaired and parse_repaired.strip() != code.strip():
                                code = self._sanitize_code_text(parse_repaired)
                                code = self._normalize_tactic_block_layout(code)
                                result = self.verifier.verify(code)
                        code, result, repair_used = self._iterative_repair_with_feedback(
                            formal_statement=stmt,
                            code=code,
                            result=result,
                            max_steps=max(0, int(getattr(cfg, "code_repair_steps", 0))),
                        )
                        if repair_used > 0:
                            attempt.attempts += repair_used
                            attempt.all_codes.append(code)
                        code, result, sorry_fill_used = self._iterative_fill_sorries_with_goals(
                            theorem_header=header,
                            code=code,
                            result=result,
                            max_steps=max(0, int(getattr(cfg, "code_repair_steps", 0))),
                            candidates=max(1, int(getattr(cfg, "sorry_fill_candidates", 3))),
                        )
                        if sorry_fill_used > 0:
                            attempt.attempts += sorry_fill_used
                            attempt.all_codes.append(code)
                        code, result, final_mile_used = self._final_mile_close_sorries(
                            formal_statement=stmt,
                            code=code,
                            result=result,
                            max_steps=2,
                        )
                        if final_mile_used > 0:
                            attempt.attempts += final_mile_used
                            attempt.all_codes.append(code)

                    if self.tracer:
                        signal = self._signal_metrics(result)
                        self.tracer.log(
                            "draft_formalize_attempt",
                            {
                                "problem_id": problem_id,
                                "strategy": self.name,
                                "round_idx": round_idx,
                                "draft_idx": draft_idx,
                                "sample_idx": sample_idx,
                                "placeholder_or_hole": placeholder_hit,
                                "complete": result.complete,
                                "success": result.success,
                                "n_errors": len(result.errors),
                                "n_sorries": len(result.sorries),
                                "n_goals": len(result.goals),
                                "state_signal": signal,
                                "value_score": self._value_score(result),
                                "elapsed_s": result.elapsed,
                            },
                        )

                    if result.complete:
                        attempt.complete = True
                        attempt.code = code
                        attempt.best_result = result
                        attempt.metadata["rounds_used"] = round_idx + 1
                        attempt.metadata["draft_count"] = len(draft_texts)
                        return attempt

                    if best_result is None or self._composite_score(result, code) > self._composite_score(best_result, best_code):
                        best_result = result
                        best_code = code

                    fb = self._build_feedback(result, int(cfg.max_feedback_chars))
                    if bool(getattr(cfg, "enable_global_gap_feedback", True)):
                        gap_fb = self._build_global_gap_feedback(code, result)
                        if gap_fb:
                            fb = f"{fb}\n\n{gap_fb}".strip() if fb else gap_fb
                    if placeholder_hit:
                        fb = (
                            "Previous attempt collapsed to a placeholder/sorry skeleton.\n"
                            "Next revision MUST provide concrete Lean steps (`have`, `rw`, `exact`, `linarith`, etc.)\n"
                            "and MUST NOT return theorem+sorry-only bodies.\n\n"
                            f"{fb}"
                        ).strip()
                    if fb and (not best_feedback_for_draft or len(fb) > len(best_feedback_for_draft)):
                        best_feedback_for_draft = fb

                if best_feedback_for_draft and round_idx + 1 < rounds:
                    revise_prompt = build_revise_draft_prompt(stmt, draft, best_feedback_for_draft)
                    revised = self.model.generate_single(
                        revise_prompt,
                        n=1,
                        temperature=self.config.model.temperature,
                        max_tokens=min(2048, self.config.model.max_tokens),
                        chat=use_chat,
                    )
                    if revised:
                        revised_drafts.append(revised[0].strip())
                        if self.tracer:
                            self.tracer.log(
                                "draft_revised",
                                {
                                    "problem_id": problem_id,
                                    "strategy": self.name,
                                    "round_idx": round_idx,
                                    "draft_idx": draft_idx,
                                },
                            )

            if revised_drafts:
                draft_texts = self._dedup_nonempty(revised_drafts)
                if not draft_texts:
                    break
            else:
                break

        attempt.best_result = best_result
        attempt.code = best_code
        attempt.metadata["rounds_used"] = rounds
        attempt.metadata["draft_count"] = len(draft_texts)
        return attempt

    @staticmethod
    def _dedup_nonempty(items: list[str]) -> list[str]:
        out: list[str] = []
        seen = set()
        for s in items:
            t = (s or "").strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out

    @staticmethod
    def _build_feedback(result: VerifyResult, max_chars: int) -> str:
        chunks: list[str] = []
        if result.errors:
            chunks.append("Errors:")
            for e in result.errors[:3]:
                msg = (e.get("data", "") or "").strip()
                if msg:
                    chunks.append(f"- {msg}")
        if result.goals:
            chunks.append("Remaining goals:")
            for g in result.goals[:2]:
                chunks.append(g.strip())
        if result.sorries:
            chunks.append(f"Sorries count: {len(result.sorries)}")
        text = "\n".join(chunks).strip()
        return text[:max(200, max_chars)]

    def _repair_placeholder_code(self, formal_statement: str, partial_code: str) -> str:
        """Ask model to fill `?_`/holes in an otherwise structured proof."""
        prompt = (
            "Fill all proof holes in the following Lean 4 code.\n"
            "Return ONLY one fenced Lean code block.\n"
            "Do not keep any `?_`, `sorry`, `admit`, or placeholders.\n"
            "Keep theorem statement unchanged.\n\n"
            "Target environment: Lean 4 + older Mathlib-compatible style.\n\n"
            "Theorem statement:\n"
            f"```lean4\n{formal_statement}\n```\n\n"
            "Partial code to repair:\n"
            f"```lean4\n{partial_code}\n```"
        )
        use_chat = self.config.model.use_chat_template
        outs = self.model.generate_single(
            prompt,
            n=1,
            temperature=max(0.0, min(0.4, float(self.config.model.temperature))),
            max_tokens=min(2048, self.config.model.max_tokens),
            chat=use_chat,
        )
        if not outs:
            return partial_code
        fixed = self.model.extract_lean_code(outs[0])
        if not fixed:
            return partial_code
        merged = self._assemble_proof(self.extract_theorem_header(partial_code), fixed)
        return merged if merged.strip() else partial_code

    def _repair_parse_error_code(self, formal_statement: str, broken_code: str, error_message: str) -> str:
        """Ask model to minimally repair syntax/parsing issues in Lean code."""
        prompt = (
            "The following Lean 4 code fails to parse. Fix ONLY syntax/format/layout issues.\n"
            "Do not redesign the proof.\n"
            "Return ONLY one fenced Lean code block.\n"
            "Do not output `sorry`, `admit`, or `?_`.\n\n"
            f"Parse error:\n{error_message}\n\n"
            "Theorem statement:\n"
            f"```lean4\n{formal_statement}\n```\n\n"
            "Broken code:\n"
            f"```lean4\n{broken_code}\n```"
        )
        use_chat = self.config.model.use_chat_template
        outs = self.model.generate_single(
            prompt,
            n=1,
            temperature=max(0.0, min(0.2, float(self.config.model.temperature))),
            max_tokens=min(1536, self.config.model.max_tokens),
            chat=use_chat,
        )
        if not outs:
            return broken_code
        fixed = self.model.extract_lean_code(outs[0])
        if not fixed:
            return broken_code
        merged = self._assemble_proof(self.extract_theorem_header(broken_code), fixed)
        return merged if merged.strip() else broken_code

    def _iterative_repair_with_feedback(
        self,
        formal_statement: str,
        code: str,
        result: VerifyResult,
        max_steps: int,
    ) -> tuple[str, VerifyResult, int]:
        """Repair proof code using Lean feedback in multiple turns."""
        if max_steps <= 0:
            return code, result, 0
        used = 0
        current_code = code
        current_result = result
        use_chat = self.config.model.use_chat_template

        for _ in range(max_steps):
            if current_result.complete:
                break
            if not (current_result.errors or current_result.sorries or current_result.goals):
                break
            if bool(getattr(self.config.draft_formalize, "enable_localized_feedback", True)):
                feedback = self._build_localized_feedback(
                    code=current_code,
                    result=current_result,
                    max_chars=int(getattr(self.config.draft_formalize, "max_feedback_chars", 1500)),
                )
            else:
                feedback = self._build_feedback(
                    current_result,
                    int(getattr(self.config.draft_formalize, "max_feedback_chars", 1500)),
                )
            if not feedback:
                break
            prompt = build_code_repair_prompt(
                formal_statement=formal_statement,
                failed_code=current_code,
                lean_feedback=feedback,
            )
            outs = self.model.generate_single(
                prompt,
                n=1,
                temperature=max(0.0, min(0.35, float(self.config.model.temperature))),
                max_tokens=min(2048, self.config.model.max_tokens),
                chat=use_chat,
            )
            if not outs:
                break
            fixed = self.model.extract_lean_code(outs[0])
            if not fixed:
                break
            repaired_code = self._assemble_proof(self.extract_theorem_header(current_code), fixed)
            repaired_code = self._sanitize_code_text(repaired_code)
            repaired_code = self._normalize_tactic_block_layout(repaired_code)
            if repaired_code.strip() == current_code.strip():
                break
            repaired_result = self.verifier.verify(repaired_code)
            # Progress gate: only accept a repair if verifier signal improves.
            if not self._is_better_result(repaired_result, current_result):
                break
            current_code = repaired_code
            current_result = repaired_result
            used += 1
        return current_code, current_result, used

    def _iterative_fill_sorries_with_goals(
        self,
        theorem_header: str,
        code: str,
        result: VerifyResult,
        max_steps: int,
        candidates: int,
    ) -> tuple[str, VerifyResult, int]:
        """
        Fill first `sorry` by goal-conditioned local repair.
        This is subproblem decomposition guided by Lean's current sorry goals.
        """
        if max_steps <= 0:
            return code, result, 0
        used = 0
        current_code = code
        current_result = result
        use_chat = self.config.model.use_chat_template

        for _ in range(max_steps):
            if current_result.complete:
                break
            if not (current_result.success and current_result.sorries):
                break
            best_code = current_code
            best_result = current_result
            improved = False
            for sorry_idx, sorry in enumerate(current_result.sorries):
                goal = str((sorry or {}).get("goal", "")).strip()
                if not goal:
                    continue
                sorry_prefix = self._prefix_before_nth_sorry(current_code, sorry_idx)
                prompt = build_sorry_context_prompt(
                    theorem_header=theorem_header,
                    proof_prefix=sorry_prefix,
                    goal_state=goal,
                )
                # Hybrid generation:
                # - contextual mode keeps global proof consistency
                # - isolated mode focuses on clean local proof-state solving
                ctx_n = max(1, candidates // 2)
                iso_n = max(1, candidates - ctx_n)
                outs_ctx = self.model.generate_single(
                    prompt,
                    n=ctx_n,
                    temperature=max(0.0, min(0.35, float(self.config.model.temperature))),
                    max_tokens=512,
                    chat=use_chat,
                )
                outs_iso = self.model.generate_single(
                    build_sorry_isolated_prompt(goal),
                    n=iso_n,
                    temperature=max(0.0, min(0.35, float(self.config.model.temperature))),
                    max_tokens=512,
                    chat=use_chat,
                )
                outs = []
                if outs_ctx:
                    outs.extend(outs_ctx)
                if outs_iso:
                    outs.extend(outs_iso)
                if not outs:
                    continue
                for raw in outs:
                    raw = (raw or "").strip()
                    replacement = self.model.extract_lean_code(raw) or raw
                    replacement = replacement.strip()
                    if not replacement:
                        continue
                    if self._has_hard_placeholder(replacement):
                        continue
                    if self._has_invalid_nonlean_markers(replacement):
                        replacement = self._strip_nonlean_artifacts(replacement)
                    cand_code = self._replace_nth_sorry_block(current_code, replacement, sorry_idx)
                    cand_code = self._sanitize_code_text(cand_code)
                    cand_code = self._normalize_tactic_block_layout(cand_code)
                    if cand_code.strip() == current_code.strip():
                        continue
                    cand_result = self.verifier.verify(cand_code)
                    if self._result_rank(cand_result) > self._result_rank(best_result):
                        best_code = cand_code
                        best_result = cand_result
                        improved = True
            if not improved:
                break
            current_code = best_code
            current_result = best_result
            used += 1
        return current_code, current_result, used

    def _error_guided_sorry_decompose(
        self,
        formal_statement: str,
        theorem_header: str,
        code: str,
        result: VerifyResult,
        max_steps: int,
        candidates: int,
    ) -> tuple[str, VerifyResult, int]:
        """
        Refine by localizing compile errors to lines, replacing them with `sorry`,
        then solving these generated subgoals with goal-conditioned filling.
        """
        if max_steps <= 0 or not result.errors:
            return code, result, 0
        # Replace all currently reported error sites by default (bounded by current error count).
        max_sites = max(1, len(result.errors or []))
        sorryified, replaced = self._replace_error_lines_with_sorry(code, result, max_sites=max_sites)
        if replaced <= 0 or sorryified.strip() == code.strip():
            return code, result, 0
        sorryified = self._sanitize_code_text(sorryified)
        sorryified = self._normalize_tactic_block_layout(sorryified)
        sorryified_result = self.verifier.verify(sorryified)
        used = 0
        if not (sorryified_result.success and sorryified_result.sorries):
            return code, result, used
        decomp_code, decomp_result, fill_used = self._iterative_fill_sorries_with_goals(
            theorem_header=theorem_header,
            code=sorryified,
            result=sorryified_result,
            max_steps=max_steps,
            candidates=candidates,
        )
        used += fill_used
        if self._result_rank(decomp_result) > self._result_rank(result):
            return decomp_code, decomp_result, used
        return code, result, used

    def _final_mile_close_sorries(
        self,
        formal_statement: str,
        code: str,
        result: VerifyResult,
        max_steps: int = 2,
    ) -> tuple[str, VerifyResult, int]:
        """
        Final-mile closure for near-complete proofs:
        when Lean already passes but still has a small number of sorries,
        ask the model to close all remaining goals without introducing any placeholders.
        """
        if max_steps <= 0:
            return code, result, 0
        if not (result.success and result.sorries and len(result.sorries) <= 2):
            return code, result, 0

        use_chat = self.config.model.use_chat_template
        current_code = code
        current_result = result
        used = 0
        for _ in range(max_steps):
            if current_result.complete:
                break
            if not (current_result.success and current_result.sorries):
                break
            goals = []
            for i, s in enumerate(current_result.sorries[:3], start=1):
                g = str((s or {}).get("goal", "")).strip()
                if g:
                    goals.append(f"[goal {i}]\n{g}")
            feedback = (
                "FINAL-MILE MODE:\n"
                "The proof already typechecks except for remaining sorry goals.\n"
                "Close ALL remaining goals now.\n"
                "Do NOT output `sorry`, `admit`, `all_goals sorry`, or placeholders.\n\n"
                + ("\n\n".join(goals) if goals else "No explicit goals returned.")
            )
            prompt = build_final_mile_tactic_prompt(
                failed_code=current_code,
                goal_state=feedback,
            )
            outs = self.model.generate_single(
                prompt,
                n=2,
                temperature=max(0.0, min(0.25, float(self.config.model.temperature))),
                max_tokens=min(3072, self.config.model.max_tokens),
                chat=use_chat,
            )
            if not outs:
                break

            best_code = current_code
            best_result = current_result
            improved = False
            whitelist_hit = False
            for out in outs:
                fixed = self.model.extract_lean_code(out)
                if not fixed:
                    continue
                if not self._is_tactic_block_whitelisted(fixed):
                    continue
                whitelist_hit = True
                cand_code = self._assemble_proof(self.extract_theorem_header(current_code), fixed)
                cand_code = self._sanitize_code_text(cand_code)
                cand_code = self._normalize_tactic_block_layout(cand_code)
                if self._is_sorry_collapse_pattern(cand_code):
                    continue
                cand_result = self.verifier.verify(cand_code)
                if self._is_better_result(cand_result, best_result):
                    best_code = cand_code
                    best_result = cand_result
                    improved = True
            if not whitelist_hit:
                fallback_prompt = build_code_repair_prompt(
                    formal_statement=formal_statement,
                    failed_code=current_code,
                    lean_feedback=feedback,
                )
                fallback_outs = self.model.generate_single(
                    fallback_prompt,
                    n=1,
                    temperature=max(0.0, min(0.2, float(self.config.model.temperature))),
                    max_tokens=min(3072, self.config.model.max_tokens),
                    chat=use_chat,
                )
                for out in fallback_outs:
                    fixed = self.model.extract_lean_code(out)
                    if not fixed:
                        continue
                    cand_code = self._assemble_proof(self.extract_theorem_header(current_code), fixed)
                    cand_code = self._sanitize_code_text(cand_code)
                    cand_code = self._normalize_tactic_block_layout(cand_code)
                    if self._is_sorry_collapse_pattern(cand_code):
                        continue
                    cand_result = self.verifier.verify(cand_code)
                    if self._is_better_result(cand_result, best_result):
                        best_code = cand_code
                        best_result = cand_result
                        improved = True
            if not improved:
                break
            current_code = best_code
            current_result = best_result
            used += 1
        return current_code, current_result, used

    @staticmethod
    def _is_tactic_block_whitelisted(text: str) -> bool:
        allowed = (
            "intro", "intros", "refine", "exact", "apply",
            "have", "suffices",
            "rw", "simp", "simpa",
            "aesop", "constructor", "left", "right", "rcases", "cases",
            "calc", "nth_rewrite",
            "linarith", "nlinarith", "omega",
            "ring", "noncomm_ring",
            "trivial", "assumption", "rfl",
            "·", "|", "{", "}",
        )
        banned = ("sorry", "admit", "all_goals sorry", "repeat sorry")
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            return False
        for ln in lines:
            low = ln.lower()
            if any(b in low for b in banned):
                return False
            if ln.startswith("--") or ln.startswith("/-"):
                return False
            if ln.startswith("theorem ") or ln.startswith("lemma ") or ln.startswith("import "):
                return False
            if not any(ln.startswith(h) for h in allowed):
                return False
        return True

    @staticmethod
    def _has_hard_placeholder(code: str) -> bool:
        lower = code.lower()
        bad_tokens = (
            " admit",
            "\nadmit",
            "by\n  -- todo",
            "by\n  -- sorry",
        )
        return any(tok in lower for tok in bad_tokens)

    @staticmethod
    def _has_invalid_nonlean_markers(code: str) -> bool:
        lower = code.lower()
        return (
            "<think>" in lower
            or "</think>" in lower
            or "\n  ..." in lower
            or "\n..." in lower
        )

    @staticmethod
    def _strip_nonlean_artifacts(code: str) -> str:
        lines = []
        skip_think = False
        for ln in code.splitlines():
            low = ln.lower()
            if "<think>" in low:
                skip_think = True
                continue
            if "</think>" in low:
                skip_think = False
                continue
            if skip_think:
                continue
            stripped = ln.strip()
            if stripped == "...":
                continue
            lines.append(ln)
        return "\n".join(lines).strip()

    @staticmethod
    def _result_rank(result: VerifyResult) -> tuple[int, int, int]:
        # higher is better: complete > pass/no-error > fewer sorries/errors
        return (
            2 if result.complete else (1 if result.success else 0),
            -len(result.errors or []),
            -len(result.sorries or []),
        )

    @staticmethod
    def _prefix_before_first_sorry(code: str) -> str:
        idx = code.find("sorry")
        if idx < 0:
            return code
        return code[:idx].rstrip()

    @staticmethod
    def _replace_first_sorry_block(code: str, replacement: str) -> str:
        return DraftFormalizeStrategy._replace_nth_sorry_block(code, replacement, 0)

    @staticmethod
    def _replace_nth_sorry_block(code: str, replacement: str, target_idx: int) -> str:
        lines = code.splitlines()
        repl_lines = [ln.rstrip() for ln in replacement.splitlines() if ln.strip()]
        if not repl_lines:
            return code
        seen = -1
        for i, ln in enumerate(lines):
            if "sorry" not in ln:
                continue
            seen += 1
            if seen != target_idx:
                continue
            indent = ln[: len(ln) - len(ln.lstrip())]
            normalized = [indent + r.lstrip() for r in repl_lines]
            lines = lines[:i] + normalized + lines[i + 1 :]
            return "\n".join(lines)
        return code

    @staticmethod
    def _prefix_before_nth_sorry(code: str, target_idx: int) -> str:
        start = 0
        for idx in range(target_idx + 1):
            pos = code.find("sorry", start)
            if pos < 0:
                return code
            if idx == target_idx:
                return code[:pos].rstrip()
            start = pos + len("sorry")
        return code.rstrip()

    @staticmethod
    def _first_error_message(result: VerifyResult) -> str:
        if not result.errors:
            return ""
        return str(result.errors[0].get("data", "") or "").strip()

    @staticmethod
    def _replace_error_lines_with_sorry(code: str, result: VerifyResult, max_sites: int = 4) -> tuple[str, int]:
        """
        Replace selected error lines with `sorry` as local repair anchors.
        """
        if not result.errors:
            return code, 0
        lines = code.splitlines()
        by_line = next((i for i, ln in enumerate(lines) if ":= by" in ln), -1)
        line_ids: list[int] = []
        for err in result.errors:
            pos = err.get("pos") or {}
            ln = pos.get("line")
            if not isinstance(ln, int):
                continue
            idx = ln - 1
            if idx <= by_line or idx < 0 or idx >= len(lines):
                continue
            line_ids.append(idx)
        uniq = []
        seen = set()
        for idx in line_ids:
            if idx in seen:
                continue
            seen.add(idx)
            uniq.append(idx)
        uniq = uniq[: max(1, max_sites)]
        replaced = 0
        for idx in uniq:
            original = lines[idx]
            if "sorry" in original:
                continue
            indent = original[: len(original) - len(original.lstrip())]
            lines[idx] = f"{indent}sorry"
            replaced += 1
        return "\n".join(lines), replaced

    def _build_localized_feedback(self, code: str, result: VerifyResult, max_chars: int) -> str:
        """
        Build compact, line-localized feedback instead of full noisy dump.
        """
        code_lines = code.splitlines()
        chunks: list[str] = []
        if result.errors:
            chunks.append("Top compile errors with local context:")
            for err in result.errors[:4]:
                pos = err.get("pos") or {}
                ln = pos.get("line")
                msg = str(err.get("data", "") or "").strip()
                if isinstance(ln, int) and 1 <= ln <= len(code_lines):
                    src = code_lines[ln - 1].strip()
                    chunks.append(f"- line {ln}: {msg}")
                    if src:
                        chunks.append(f"  code: {src[:160]}")
                elif msg:
                    chunks.append(f"- {msg}")
        if result.goals:
            chunks.append("Remaining goals:")
            for g in result.goals[:2]:
                chunks.append(g.strip())
        if result.sorries:
            chunks.append(f"Sorries count: {len(result.sorries)}")
        text = "\n".join(chunks).strip()
        return text[:max(200, max_chars)]

    def _needs_parse_repair(self, result: VerifyResult) -> bool:
        msg = self._first_error_message(result).lower()
        if not msg:
            return False
        return (
            "expected token" in msg
            or "unexpected token" in msg
            or "expected '{' or indented tactic sequence" in msg
        )

    @staticmethod
    def _normalize_tactic_block_layout(code: str) -> str:
        """
        Heuristic layout fix:
        - If theorem has `:= by`, ensure following non-empty lines are indented as tactic lines.
        """
        marker = ":= by"
        if marker not in code:
            return code
        lines = code.splitlines()
        out: list[str] = []
        in_tactic_block = False
        for ln in lines:
            if not in_tactic_block:
                out.append(ln)
                if marker in ln:
                    in_tactic_block = True
                continue
            if not ln.strip():
                out.append(ln)
                continue
            stripped = ln.lstrip()
            # Keep comments aligned as tactics.
            if ln.startswith("  "):
                out.append(ln)
            else:
                out.append(f"  {stripped}")
        return "\n".join(out)

    @staticmethod
    def _sanitize_code_text(code: str) -> str:
        """Remove hidden/control characters that often break Lean parsing."""
        # Keep newline and tab; strip CR and zero-width chars.
        banned = {"\u200b", "\u200c", "\u200d", "\ufeff"}
        out_chars: list[str] = []
        for ch in code.replace("\r", ""):
            if ch in banned:
                continue
            o = ord(ch)
            if o < 32 and ch not in ("\n", "\t"):
                continue
            out_chars.append(ch)
        return "".join(out_chars)

    def _assemble_proof(self, header: str, extracted: str) -> str:
        # Always trust dataset theorem header and only use model-generated proof body.
        body = extracted.strip()
        if ":= by" in body:
            body = body.split(":= by", 1)[1].strip()
        elif body.startswith("by"):
            body = body[2:].strip()
        body = self._sanitize_extracted_proof_body(body)

        if not body:
            return header

        # Preserve model's relative indentation; only enforce base tactic indentation (>=2 spaces).
        lines = [ln.rstrip() for ln in body.splitlines() if ln.strip()]
        normalized: list[str] = []
        for ln in lines:
            lead = len(ln) - len(ln.lstrip(" "))
            if lead >= 2:
                normalized.append(ln)
            else:
                normalized.append(f"  {ln.lstrip()}")
        if not self._contains_tactic_or_sorry(normalized):
            normalized.append("  sorry")
        indented = "\n".join(normalized)
        return f"{header}\n{indented}"

    @staticmethod
    def _sanitize_extracted_proof_body(body: str) -> str:
        """
        Remove common non-proof artifacts from API outputs:
        markdown fences, import/set_option lines, and repeated declarations.
        """
        keep: list[str] = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("```"):
                continue
            if s.startswith("import "):
                continue
            if s.startswith("set_option "):
                continue
            if s.startswith("open "):
                continue
            if s.startswith("theorem ") or s.startswith("lemma ") or s.startswith("example "):
                continue
            if s == "by":
                continue
            keep.append(ln.rstrip())
        return "\n".join(keep).strip()

    @staticmethod
    def _contains_tactic_or_sorry(lines: list[str]) -> bool:
        tactic_heads = (
            "intro",
            "rintro",
            "have",
            "let ",
            "set ",
            "refine",
            "exact",
            "apply",
            "rw",
            "simp",
            "linarith",
            "nlinarith",
            "omega",
            "ring",
            "noncomm_ring",
            "constructor",
            "left",
            "right",
            "cases",
            "rcases",
            "obtain",
            "by_contra",
            "tauto",
            "aesop",
            "assumption",
            "trivial",
            "finish",
            "sorry",
        )
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("--") or s.startswith("/-"):
                continue
            if any(s.startswith(h) for h in tactic_heads):
                return True
            if s in ("rfl", "decide"):
                return True
        return False

    @staticmethod
    def _is_trivial_sorry_skeleton(code: str) -> bool:
        """
        Detect degenerate proof bodies that effectively contain only comments and `sorry`.
        """
        marker = ":= by"
        if marker not in code:
            return False
        body = code.split(marker, 1)[1]
        meaningful: list[str] = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("--") or s.startswith("/-"):
                continue
            meaningful.append(s)
        return bool(meaningful) and all(s == "sorry" for s in meaningful)

    @staticmethod
    def _is_sorry_collapse_pattern(code: str) -> bool:
        """
        Detect non-trivial looking but effectively collapsed proofs, e.g.:
        - `all_goals sorry`
        - many sorry lines with very few concrete tactic lines
        """
        marker = ":= by"
        if marker not in code:
            return False
        body = code.split(marker, 1)[1]
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if not lines:
            return False

        lowered = [ln.lower() for ln in lines]
        if any("all_goals sorry" in ln for ln in lowered):
            return True
        if any("repeat' sorry" in ln or "repeat sorry" in ln for ln in lowered):
            return True

        non_comment = [ln for ln in lines if not (ln.startswith("--") or ln.startswith("/-"))]
        if not non_comment:
            return False
        sorry_like = [ln for ln in non_comment if ln == "sorry" or ln.endswith(" sorry")]
        concrete = [ln for ln in non_comment if ln not in sorry_like]
        # If sorry dominates and there are very few concrete lines, treat as collapse.
        if len(sorry_like) >= 2 and len(concrete) <= 2:
            return True
        return False

    @staticmethod
    def _score(result: VerifyResult) -> float:
        if result.complete:
            return 100.0
        if result.success:
            return 10.0 - len(result.sorries)
        return -len(result.errors)

    @staticmethod
    def _sketch_structure_score(code: str) -> float:
        text = (code or "").lower()
        have_cnt = text.count("\n  have ") + text.count("\nhave ")
        suffices_cnt = text.count("suffices ")
        calc_cnt = text.count("\n  calc") + text.count("\ncalc")
        case_cnt = text.count("by_cases ") + text.count("cases ")
        sorry_cnt = text.count("sorry")
        return (
            1.2 * min(6, have_cnt)
            + 0.8 * min(3, suffices_cnt)
            + 0.6 * min(3, calc_cnt)
            + 0.4 * min(4, case_cnt)
            - 0.5 * min(8, sorry_cnt)
        )

    @staticmethod
    def _distance_to_complete(result: VerifyResult) -> float:
        s = DraftFormalizeStrategy._signal_metrics(result)
        return (
            2.5 * s["syntax_errors"]
            + 2.0 * s["unknown_identifier_errors"]
            + 1.5 * s["type_errors"]
            + 1.2 * s["goal_count"]
            + 1.0 * s["sorry_count"]
            + 0.6 * s["error_count"]
        )

    @staticmethod
    def _composite_score(result: VerifyResult, code: str) -> float:
        # Combine verifier signal with global proof-structure signal.
        return (
            DraftFormalizeStrategy._value_score(result)
            + 0.8 * DraftFormalizeStrategy._sketch_structure_score(code)
            - 0.5 * DraftFormalizeStrategy._distance_to_complete(result)
        )

    def _build_global_gap_feedback(self, code: str, result: VerifyResult) -> str:
        s = self._signal_metrics(result)
        structure = self._sketch_structure_score(code)
        dist = self._distance_to_complete(result)
        hints: list[str] = []
        if s["syntax_errors"] > 0 or s["unknown_identifier_errors"] > 0:
            hints.append("Fix syntax/API identifier issues first, then continue proof closure.")
        if s["sorry_count"] >= 2 and structure < 1.5:
            hints.append("Decomposition is weak: add 2-3 bridge lemmas (`have`/`suffices`) before closure.")
        if s["goal_count"] > 0 and s["sorry_count"] == 0:
            hints.append("Unclosed goals remain: use direct closing tactics (`exact`/`rw`/`simp`/`linarith`).")
        if s["sorry_count"] == 1:
            hints.append("Only one subgoal remains; focus on final-mile closure.")
        summary = (
            "Global gap signal:\n"
            f"- structure_score={structure:.2f}\n"
            f"- distance_to_complete={dist:.2f}\n"
            f"- syntax={s['syntax_errors']}, unknown_id={s['unknown_identifier_errors']}, "
            f"type={s['type_errors']}, goals={s['goal_count']}, sorries={s['sorry_count']}\n"
        )
        if hints:
            summary += "Action hints:\n- " + "\n- ".join(hints)
        return summary.strip()

    @staticmethod
    def _signal_metrics(result: VerifyResult) -> dict:
        errors = result.errors or []
        lower_msgs = [str(e.get("data", "") or "").lower() for e in errors]
        return {
            "syntax_errors": sum(1 for m in lower_msgs if "expected token" in m or "unexpected token" in m),
            "unknown_identifier_errors": sum(
                1 for m in lower_msgs if "unknown identifier" in m or "unknown constant" in m or "not found" in m
            ),
            "type_errors": sum(1 for m in lower_msgs if "type mismatch" in m or "failed to synthesize" in m),
            "goal_count": len(result.goals or []),
            "sorry_count": len(result.sorries or []),
            "error_count": len(errors),
        }

    @staticmethod
    def _value_score(result: VerifyResult) -> float:
        s = DraftFormalizeStrategy._signal_metrics(result)
        if result.complete:
            return 1000.0
        score = 0.0
        if result.success:
            score += 100.0
        score -= 8.0 * s["syntax_errors"]
        score -= 5.0 * s["unknown_identifier_errors"]
        score -= 3.0 * s["type_errors"]
        score -= 1.5 * s["goal_count"]
        score -= 1.0 * s["sorry_count"]
        score -= 0.5 * s["error_count"]
        return score

    @staticmethod
    def _is_better_result(new: VerifyResult, old: VerifyResult) -> bool:
        """Strict improvement predicate for accepting in-place repairs."""
        if new.complete and not old.complete:
            return True
        old_rank = DraftFormalizeStrategy._result_rank(old)
        new_rank = DraftFormalizeStrategy._result_rank(new)
        if new_rank > old_rank:
            return True
        # Same rank: require strictly higher verifier value score.
        return DraftFormalizeStrategy._value_score(new) > DraftFormalizeStrategy._value_score(old) + 1e-6
