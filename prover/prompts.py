"""
Prompt templates for different proof strategies.
Designed to improve mathematical reasoning by providing structured guidance
rather than just "complete the proof."
"""


WHOLE_PROOF_COT = """\
Complete the following Lean 4 code with a formal proof.

```lean4
{formal_statement}
```

Before writing the proof, think step by step:
1. What is the mathematical content of this theorem?
2. What proof strategy should be used (direct computation, induction, contradiction, case analysis, algebraic manipulation)?
3. What key Mathlib lemmas or tactics are likely needed?
4. Outline the proof structure.

Then provide the complete Lean 4 proof."""


WHOLE_PROOF_DIRECT = """\
Complete the following Lean 4 code:

```lean4
{formal_statement}
```
"""


# Two-stage API prompting: first natural-language draft, then formalization.
DRAFT_NL_PROOF = """\
You are helping with Lean 4 theorem proving.

Given this theorem statement, write a concise but concrete natural-language proof draft.
Focus on key lemmas, algebraic transformations, and exact proof structure.
Do not output Lean code in this step.

```lean4
{formal_statement}
```
"""


FORMALIZE_FROM_DRAFT = """\
Convert the following natural-language proof draft into Lean 4 code.
Output ONLY one fenced Lean code block.
Do not include explanation outside the code block.

Important constraints for this project:
- Target environment is Lean 4 + an older Mathlib snapshot.
- Prefer conservative, stable APIs and basic tactics over "fancy" or newly-added names.
- Do NOT invent theorem/constant names.
- Do NOT output `sorry`, `admit`, `by
  -- TODO`, `?_`, or placeholder proof holes.
- If a named lemma is uncertain, use a robust tactic path (`have`, `rw`, `simp`, `linarith`, `omega`, `exact`) that is likely to exist.

Theorem to prove:
```lean4
{formal_statement}
```

Natural-language draft:
{draft_text}
"""

SKETCH_FROM_DRAFT = """\
Translate the natural-language proof into a Lean 4 lemma-style sketch.
Output ONLY one fenced Lean code block.

This is a decomposition step (not final closure):
- Keep theorem statement unchanged.
- Use at least {min_lemmas} intermediate lemma steps (`have` / `suffices` / local claims).
- It is allowed to keep local `sorry` holes in sub-lemmas.
- Do NOT use `admit`, `?_`, markdown comments, or invented constants.
- Prefer stable old-Mathlib compatible tactics and statements.

Theorem:
```lean4
{formal_statement}
```

Natural-language draft:
{draft_text}
"""


REVISE_DRAFT_WITH_FEEDBACK = """\
The previous Lean formalization attempt failed. Revise the natural-language proof draft.
Keep it short, executable, and aligned with Lean tactics/lemmas.
Do not output Lean code in this step.

Revision rules:
- Assume old Mathlib compatibility (avoid newly introduced API names).
- If feedback says unknown constant/identifier, replace that step with a tactic-level fallback.
- Keep the proof skeleton minimal and complete; no placeholders.
- Do NOT output a theorem-level sorry skeleton. Every key step must be concretely actionable in Lean.
- If the previous attempt stalled on one subgoal, explicitly add a local bridge lemma step for that subgoal.

Theorem:
```lean4
{formal_statement}
```

Current draft:
{draft_text}

Lean feedback:
```
{lean_feedback}
```
"""

REPAIR_CODE_WITH_FEEDBACK = """\
You are repairing a Lean 4 proof using verifier feedback.
Return ONLY one fenced Lean code block.

Requirements:
- Keep theorem statement unchanged.
- Prioritize syntactic correctness and Lean-checkable steps.
- You may keep intermediate `sorry` if full closure is hard, but reduce errors/goals.
- Prefer stable tactics/lemmas and avoid inventing unknown constants.

Theorem:
```lean4
{formal_statement}
```

Current proof attempt:
```lean4
{failed_code}
```

Lean feedback:
```
{lean_feedback}
```
"""


# Goedel-Prover-V2 official README (Quick Start) user message — standard mode / Pass@32
GOEDEL_V2_OFFICIAL_USER = """\
Complete the following Lean 4 code:

```lean4
{formal_statement}
```

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof.
"""


STEPWISE_INITIAL = """\
I need to prove the following theorem in Lean 4 step by step.

```lean4
{formal_statement}
```

The current proof state (goals to prove) is:
```
{goal_state}
```
{whole_proof_hint}
Suggest the SINGLE BEST next tactic to apply. Output ONLY the tactic, nothing else.
If the goal can be closed directly, use the appropriate closing tactic (e.g., `norm_num`, `omega`, `simp`, `ring`, `linarith`, `decide`, `exact ...`, `rfl`).
If the goal needs decomposition, use a structuring tactic (e.g., `constructor`, `intro`, `cases`, `induction`, `by_contra`, `have ... := ...`, `suffices ... by ...`).
"""


STEPWISE_WITH_CONTEXT = """\
I am proving the following theorem in Lean 4:

```lean4
{formal_statement}
```

Tactics applied so far:
{tactics_so_far}

Current proof state:
```
{goal_state}
```

{error_context}
{whole_proof_hint}
Suggest the SINGLE BEST next tactic. Output ONLY the tactic."""


REFINEMENT_ANALYZE = """\
The following Lean 4 proof attempt failed:

```lean4
{failed_code}
```

Compilation error:
```
{error_message}
```

Analyze WHY the proof failed. Focus on:
1. Which specific tactic or step caused the error?
2. What is the proof state at the point of failure?
3. What alternative approach could fix this?

Then provide a COMPLETE corrected proof."""


REFINEMENT_TARGETED = """\
The following Lean 4 proof is almost correct but fails at a specific point:

```lean4
{partial_proof}
```

The proof compiles up to this point, but the remaining goal is:
```
{remaining_goal}
```

Provide ONLY the tactics needed to close this remaining goal. Output the tactics, one per line."""


SORRY_CONTEXT_FILL = """\
I am filling a `sorry` gap in a Lean 4 proof. Here is the theorem header:

```lean4
{theorem_header}
```

The proof so far (up to the sorry position):
```lean4
{proof_prefix}
```

The precise goal state at this sorry position is:
```
{goal_state}
```

Provide ONLY the tactic(s) needed to close this goal. Output the tactics, one per line.
Do NOT include `sorry`. The tactics should resolve the goal completely."""

SORRY_ISOLATED_SUBGOAL = """\
I am solving a Lean 4 subgoal in isolated mode.

You are given the local proof state from Lean (context + target). Solve ONLY this subgoal.
Do NOT output theorem declarations or imports.
Do NOT output `sorry`, `admit`, placeholders, or comments.
Output ONLY tactic lines.

Subgoal proof state:
```
{goal_state}
```
"""

FINAL_MILE_TACTIC_ONLY = """\
You are in FINAL-MILE closure mode for Lean 4.

The proof already typechecks except for remaining goals.
Close the goals using ONLY stable tactic lines.
Do NOT output theorem declarations, comments, imports, or placeholders.
Do NOT output `sorry`, `admit`, `all_goals sorry`, `repeat sorry`.

Allowed tactic heads (preferred):
- intro, intros, refine, exact, apply
- have, suffices
- rw, simp, simpa
- aesop, constructor, left, right, rcases, cases
- calc, nth_rewrite
- linarith, nlinarith, omega
- ring, noncomm_ring
- trivial, assumption, rfl

Current proof (for context):
```lean4
{failed_code}
```

Remaining goals:
```
{goal_state}
```

Output ONLY tactic lines to close goals.
"""


REFINEMENT_ERROR_TYPED = """\
The following Lean 4 proof failed with a {error_category} error:

```lean4
{failed_code}
```

Error at line {error_line}:
```
{error_message}
```

{fix_guidance}

Provide a COMPLETE corrected proof."""


STRATEGY_SELECTION = """\
Given this Lean 4 theorem statement, classify the best proof strategy:

```lean4
{formal_statement}
```

Choose ONE strategy:
- COMPUTATION: numeric computation, decidable propositions, finite case analysis
- ALGEBRAIC: ring/field manipulations, polynomial arithmetic
- INDUCTION: mathematical induction, strong induction, well-founded recursion
- ANALYSIS: epsilon-delta, limits, continuity, sequences
- COMBINATORIAL: counting, pigeonhole, graph theory
- NUMBER_THEORY: divisibility, modular arithmetic, primes
- LINEAR_ALGEBRA: vector spaces, matrices, determinants
- DIRECT: simple logical deductions, direct application of definitions

Output ONLY the strategy name."""


ERROR_FIX_GUIDANCE = {
    "type_mismatch": (
        "This is a type mismatch error. The expected type does not match the actual type. "
        "Check: (1) Are you using the correct lemma? (2) Do you need explicit type casts "
        "(e.g., Nat.cast, Int.cast)? (3) Are there implicit arguments that need to be specified?"
    ),
    "unknown_identifier": (
        "An identifier was not found. Check: (1) Is the Mathlib lemma name correct? "
        "Use `exact?` or `apply?` mentally. (2) Has the API changed in recent Mathlib versions? "
        "(3) Do you need to `open` a namespace?"
    ),
    "tactic_failed": (
        "A tactic failed to make progress. Check: (1) Is `simp` missing needed lemmas "
        "(try `simp [lemma_name]`)? (2) Would `omega`, `norm_num`, or `ring` be more appropriate? "
        "(3) Does the goal need simplification before this tactic applies?"
    ),
    "other": (
        "Analyze the error carefully. Consider trying a completely different proof approach "
        "if the current one seems fundamentally flawed."
    ),
}


def format_prompt(template: str, **kwargs) -> str:
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", str(value))
    return template


def build_whole_proof_prompt(formal_statement: str, use_cot: bool = True) -> str:
    template = WHOLE_PROOF_COT if use_cot else WHOLE_PROOF_DIRECT
    return format_prompt(template, formal_statement=formal_statement)


def build_goedel_v2_official_prompt(formal_statement: str) -> str:
    """User content aligned with https://github.com/Goedel-LM/Goedel-Prover-V2 README Quick Start."""
    return format_prompt(GOEDEL_V2_OFFICIAL_USER, formal_statement=formal_statement)


def build_nl_draft_prompt(formal_statement: str) -> str:
    return format_prompt(DRAFT_NL_PROOF, formal_statement=formal_statement)


def build_formalize_from_draft_prompt(formal_statement: str, draft_text: str) -> str:
    return format_prompt(
        FORMALIZE_FROM_DRAFT,
        formal_statement=formal_statement,
        draft_text=draft_text,
    )


def build_sketch_from_draft_prompt(formal_statement: str, draft_text: str, min_lemmas: int = 3) -> str:
    return format_prompt(
        SKETCH_FROM_DRAFT,
        formal_statement=formal_statement,
        draft_text=draft_text,
        min_lemmas=max(1, int(min_lemmas)),
    )


def build_revise_draft_prompt(formal_statement: str, draft_text: str, lean_feedback: str) -> str:
    return format_prompt(
        REVISE_DRAFT_WITH_FEEDBACK,
        formal_statement=formal_statement,
        draft_text=draft_text,
        lean_feedback=lean_feedback,
    )

def build_code_repair_prompt(formal_statement: str, failed_code: str, lean_feedback: str) -> str:
    return format_prompt(
        REPAIR_CODE_WITH_FEEDBACK,
        formal_statement=formal_statement,
        failed_code=failed_code,
        lean_feedback=lean_feedback,
    )


def build_stepwise_prompt(
    formal_statement: str,
    goal_state: str,
    tactics_so_far: list[str] | None = None,
    error_context: str = "",
    whole_proof_hint: str = "",
) -> str:
    if not tactics_so_far:
        return format_prompt(
            STEPWISE_INITIAL,
            formal_statement=formal_statement,
            goal_state=goal_state,
            whole_proof_hint=whole_proof_hint,
        )
    tactics_str = "\n".join(f"  {t}" for t in tactics_so_far)
    return format_prompt(
        STEPWISE_WITH_CONTEXT,
        formal_statement=formal_statement,
        goal_state=goal_state,
        tactics_so_far=tactics_str,
        error_context=error_context,
        whole_proof_hint=whole_proof_hint,
    )


def build_refinement_prompt(
    failed_code: str = "",
    error_message: str = "",
    partial_proof: str = "",
    remaining_goal: str = "",
) -> str:
    if remaining_goal and partial_proof:
        return format_prompt(
            REFINEMENT_TARGETED,
            partial_proof=partial_proof,
            remaining_goal=remaining_goal,
        )
    return format_prompt(
        REFINEMENT_ANALYZE,
        failed_code=failed_code,
        error_message=error_message,
    )


def build_sorry_context_prompt(
    theorem_header: str,
    proof_prefix: str,
    goal_state: str,
    full_proof: str = "",
) -> str:
    """Context-aware prompt for filling a sorry gap with precise goal state."""
    return format_prompt(
        SORRY_CONTEXT_FILL,
        theorem_header=theorem_header,
        proof_prefix=proof_prefix,
        goal_state=goal_state,
    )


def build_sorry_isolated_prompt(goal_state: str) -> str:
    """Prompt for solving a sorry goal in isolated context."""
    return format_prompt(
        SORRY_ISOLATED_SUBGOAL,
        goal_state=goal_state,
    )


def build_final_mile_tactic_prompt(failed_code: str, goal_state: str) -> str:
    """Prompt for strict final-mile tactic-only closure."""
    return format_prompt(
        FINAL_MILE_TACTIC_ONLY,
        failed_code=failed_code,
        goal_state=goal_state,
    )


def build_error_typed_prompt(
    failed_code: str,
    error_message: str,
    error_line: str = "?",
    error_category: str = "other",
) -> str:
    """Error-classification-aware refinement prompt."""
    guidance = ERROR_FIX_GUIDANCE.get(error_category, ERROR_FIX_GUIDANCE["other"])
    return format_prompt(
        REFINEMENT_ERROR_TYPED,
        failed_code=failed_code,
        error_message=error_message,
        error_line=error_line,
        error_category=error_category,
        fix_guidance=guidance,
    )


def classify_error(error_data: str) -> str:
    """Classify a Lean compilation error into a category."""
    lower = error_data.lower()
    if "type mismatch" in lower or "has type" in lower:
        return "type_mismatch"
    if "unknown identifier" in lower or "unknown constant" in lower or "not found" in lower:
        return "unknown_identifier"
    if "tactic" in lower and ("failed" in lower or "no progress" in lower):
        return "tactic_failed"
    return "other"
