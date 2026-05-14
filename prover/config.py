"""
Configuration for the proof search framework.

Goedel-Prover-V2 (8B/32B): for paper-aligned pass@k, raise max_tokens / max_model_len
and keep use_chat_template=True; see repo docs/GOEDEL_V2_EVALUATION.md.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelConfig:
    model_path: str = "deepseek-ai/DeepSeek-Prover-V2-7B"
    backend_type: str = "vllm"  # "vllm" | "openai_compat"
    tensor_parallel_size: int = 2
    max_model_len: int = 8192
    max_tokens: int = 4096
    temperature: float = 1.0
    top_p: float = 0.95
    gpu_memory_utilization: float = 0.85
    use_chat_template: bool = True
    #: 传入 vLLM ``LLM(seed=...)``，与官方 README Quick Start 中 ``torch.manual_seed`` 对齐（可复现）
    seed: Optional[int] = None
    # OpenAI-compatible API backend settings
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    api_timeout_s: int = 120
    api_max_retries: int = 4
    api_retry_backoff_s: float = 1.5


@dataclass
class VerifierConfig:
    mathlib_path: str = "mathlib4"
    timeout: int = 120
    import_timeout: int = 120
    max_workers: int = 8
    max_heartbeats: int = 400000
    repl_recycle_after: int = 80
    imports: str = (
        "import Mathlib\nimport Aesop\n\n"
        "set_option autoImplicit false\n"
        "set_option relaxedAutoImplicit false\n"
        "set_option maxHeartbeats 4000000\n"
        "set_option maxRecDepth 10000\n\n"
        "\n"
    )


@dataclass
class StepwiseConfig:
    max_depth: int = 15
    max_width: int = 8
    max_total_nodes: int = 200
    backtrack_on_error: bool = True
    sorry_expansion: bool = True
    #: cascade 时把 whole 阶段「首个失败 tactic + REPL 报错」注入 stepwise 提示，避免模型重复踩坑
    inject_prior_failure_hints: bool = True
    # Error-type aware tactic filtering/re-ranking
    enable_typed_action_masking: bool = True
    action_mask_min_candidates: int = 2
    action_mask_soft_fallback: bool = True
    # For API backends, force single-line JSON tactic outputs for better parsing stability.
    api_json_tactic_mode: bool = True
    # Learned state value function (offline-fitted weights)
    use_progress_value_function: bool = True
    value_function_weights_path: str = ""
    priority_alpha: float = 1.0
    priority_beta: float = 40.0


@dataclass
class RefinementConfig:
    max_rounds: int = 3
    samples_per_round: int = 8
    focus_on_first_error: bool = True


@dataclass
class NearMissConfig:
    max_rounds: int = 5
    samples_per_round: int = 8
    baseline_results_path: str = ""
    max_sorry_gaps: int = 5


@dataclass
class WholeProofConfig:
    samples_per_problem: int = 32
    use_cot: bool = True
    #: "cot" | "direct" | "goedel_v2_official" — 与 Goedel-Prover-V2 README Quick Start 一致用 goedel_v2_official
    prompt_style: str = "cot"
    #: True = 每题 samples 次独立 n=1 请求（对齐官方 inference 的 pass@32 形状）；False = 单次 n=samples
    independent_samples: bool = False


@dataclass
class DraftFormalizeConfig:
    # Round 0: generate natural-language drafts
    draft_samples: int = 2
    # Per draft, how many Lean formalizations to sample
    formalize_samples: int = 4
    # Total rounds of (formalize -> Lean feedback -> revise draft)
    max_rounds: int = 2
    # Truncate Lean feedback injected back into draft revision prompt
    max_feedback_chars: int = 1500
    # Per candidate, additional proof-repair turns guided by Lean feedback.
    code_repair_steps: int = 2
    # Candidates per sorry-goal local repair step.
    sorry_fill_candidates: int = 3
    # Enable error-line -> sorry decomposition before local goal filling.
    enable_error_sorry_decompose: bool = True
    # Use localized line-aware feedback for code repair prompts.
    enable_localized_feedback: bool = True
    # Seed-Prover-style sketch-first branch: NL draft -> lemma-style sketch -> Lean closure.
    enable_sketch_first: bool = False
    # Sketch candidates per draft.
    sketch_samples: int = 2
    # Minimum number of intermediate lemmas expected in sketch branch.
    min_sketch_lemmas: int = 3
    # Include global proof-gap feedback (overall structure + distance-to-complete) in draft revision.
    enable_global_gap_feedback: bool = True


@dataclass
class ProverConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    stepwise: StepwiseConfig = field(default_factory=StepwiseConfig)
    refinement: RefinementConfig = field(default_factory=RefinementConfig)
    whole_proof: WholeProofConfig = field(default_factory=WholeProofConfig)
    draft_formalize: DraftFormalizeConfig = field(default_factory=DraftFormalizeConfig)
    near_miss: NearMissConfig = field(default_factory=NearMissConfig)

    strategies: list[str] = field(default_factory=lambda: ["whole_proof", "stepwise", "refinement"])
    dataset: str = "minif2f"
    #: 若为 None，使用仓库 dataset/；可指向含 miniF2F_v2s.jsonl 等文件的目录
    dataset_dir: Optional[str] = None
    output_dir: str = "results/prover"
    cuda_devices: str = ""
    seed: int = 42
    cascade: bool = False
    #: whole_proof 失败后解析首个失败 tactic，用前缀+sorry 的 goal 注入 stepwise（需 --cascade）
    warm_start_stepwise_from_whole: bool = True
    #: 仅 ``whole_proof``：先只做 LLM 推理并写入 ``output_dir/inference/*.json``，再分块并行 Lean 验证
    defer_verification: bool = False
    #: 延迟验证阶段并行进程数上限（实际还会受内存预算限制）
    verify_workers: int = 8
    #: 验证阶段可用内存上限（GB，粗粒度用于限制并行度）
    verify_memory_budget_gb: float = 500.0
    #: 粗估每个 Lean 工作进程占用（GB），用于 ``budget / per_job`` 算最大并发
    verify_memory_per_job_gb: float = 4.0
