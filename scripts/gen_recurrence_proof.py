#!/usr/bin/env python3
"""
Generate Lean4 proofs for recurrence/computation-based sorry goals.
Supports:
1. Linear recurrences: f(n) + f(n-1) = g(n) with f(k) = v
2. Recursive functions: f(n) = f(f(n+k)) for n < bound, f(n) = g(n) for n >= bound
3. Direct computation proofs using norm_num/omega chains
"""
import json
import sys


def gen_linear_recurrence_proof(
    thm_name: str,
    thm_header: str,
    f_name: str,
    recurrence_hyp: str,  # e.g., "h0"
    base_val_hyp: str,    # e.g., "h1"
    base_n: int,
    base_val: int,
    target_n: int,
    target_expr: str,     # e.g., "f 94 % 1000 = 561"
    coeff_fn,             # lambda n: n^2 (the g(n) in f(n) + f(n-1) = g(n))
    env: int = 1,
) -> dict:
    """Generate proof by computing f(base_n+1)...f(target_n) step by step."""
    lines = [f"set_option maxHeartbeats 800000 in\n{thm_header}"]
    
    val = base_val
    for n in range(base_n + 1, target_n + 1):
        new_val = coeff_fn(n) - val
        lines.append(
            f"  have h{n} : {f_name} {n} = {new_val} := "
            f"by have := {recurrence_hyp} {n}; norm_num at this; linarith"
        )
        val = new_val
    
    lines.append("  omega")
    
    return {
        "problem_id": thm_name,
        "code": "\n".join(lines),
        "env": env,
    }


def gen_recursive_fn_proof(
    thm_name: str,
    thm_header: str,
    f_name: str,
    base_hyp: str,        # hypothesis for n >= bound
    rec_hyp: str,         # hypothesis for n < bound
    bound: int,
    base_fn,              # lambda n: n-3
    rec_step: int,        # f(n) = f(f(n+step))
    target_n: int,
    target_val: int,
    env: int = 1,
) -> dict:
    """Generate proof by computing f values top-down."""
    known = {}
    
    def fval(n):
        if n in known:
            return known[n]
        if n >= bound:
            known[n] = base_fn(n)
            return known[n]
        v = fval(fval(n + rec_step))
        known[n] = v
        return v
    
    result = fval(target_n)
    assert result == target_val, f"Computed f({target_n}) = {result}, expected {target_val}"
    
    lines = [f"set_option maxRecDepth 4096 in\nset_option maxHeartbeats 1600000 in\n{thm_header}"]
    
    for n in sorted(n for n in known if n >= bound):
        lines.append(f"  have hf{n} : {f_name} {n} = {known[n]} := {base_hyp} {n} (by omega)")
    
    for n in sorted((n for n in known if n < bound), reverse=True):
        n5 = n + rec_step
        fn5 = known[n5]
        lines.append(
            f"  have hf{n} : {f_name} {n} = {known[n]} := "
            f"by rw [{rec_hyp} {n} (by omega)]; "
            f"simp only [show ({n} : ℤ) + {rec_step} = {n5} from by norm_num]; "
            f"rw [hf{n5}, hf{fn5}]"
        )
    
    lines.append(f"  exact hf{target_n}")
    
    return {
        "problem_id": thm_name,
        "code": "\n".join(lines),
        "env": env,
    }


if __name__ == "__main__":
    proofs = []
    
    proofs.append(gen_linear_recurrence_proof(
        thm_name="aime_1994_p3__gen",
        thm_header=(
            "theorem aime_1994_p3 (f : ℤ → ℤ) "
            "(h0 : ∀ x, f x + f (x - 1) = x ^ 2) "
            "(h1 : f 19 = 94) :\n"
            "    f 94 % 1000 = 561 := by"
        ),
        f_name="f",
        recurrence_hyp="h0",
        base_val_hyp="h1",
        base_n=19,
        base_val=94,
        target_n=94,
        target_expr="f 94 % 1000 = 561",
        coeff_fn=lambda n: n * n,
        env=1,
    ))
    
    proofs.append(gen_recursive_fn_proof(
        thm_name="aime_1984_p7__gen",
        thm_header=(
            "theorem aime_1984_p7 (f : ℤ → ℤ)\n"
            "    (h₀ : ∀ (n : ℤ), 1000 ≤ n → f n = n - 3)\n"
            "    (h₁ : ∀ n < 1000, f n = f (f (n + 5))) :\n"
            "    f 84 = 997 := by"
        ),
        f_name="f",
        base_hyp="h₀",
        rec_hyp="h₁",
        bound=1000,
        base_fn=lambda n: n - 3,
        rec_step=5,
        target_n=84,
        target_val=997,
        env=1,
    ))
    
    out_path = "results/minif2f/round_2/subproblem_mvp/_gen_recurrence_proofs.json"
    with open(out_path, "w") as f:
        json.dump(proofs, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(proofs)} proofs to {out_path}")
