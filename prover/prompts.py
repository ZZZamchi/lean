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


STEPWISE_INITIAL = """\
I need to prove the following theorem in Lean 4 step by step.

```lean4
{formal_statement}
```

The current proof state (goals to prove) is:
```
{goal_state}
```

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


def build_stepwise_prompt(
    formal_statement: str,
    goal_state: str,
    tactics_so_far: list[str] | None = None,
    error_context: str = "",
) -> str:
    if not tactics_so_far:
        return format_prompt(
            STEPWISE_INITIAL,
            formal_statement=formal_statement,
            goal_state=goal_state,
        )
    tactics_str = "\n".join(f"  {t}" for t in tactics_so_far)
    return format_prompt(
        STEPWISE_WITH_CONTEXT,
        formal_statement=formal_statement,
        goal_state=goal_state,
        tactics_so_far=tactics_str,
        error_context=error_context,
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
