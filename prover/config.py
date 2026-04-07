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
    tensor_parallel_size: int = 2
    max_model_len: int = 8192
    max_tokens: int = 4096
    temperature: float = 1.0
    top_p: float = 0.95
    gpu_memory_utilization: float = 0.85
    use_chat_template: bool = True


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
        "set_option maxHeartbeats 4000000 in\n"
        "set_option maxRecDepth 10000 in\n\n"
        "open BigOperators Real Nat Topology Rat\n\n"
    )


@dataclass
class StepwiseConfig:
    max_depth: int = 15
    max_width: int = 8
    max_total_nodes: int = 200
    backtrack_on_error: bool = True
    sorry_expansion: bool = True


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


@dataclass
class ProverConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    stepwise: StepwiseConfig = field(default_factory=StepwiseConfig)
    refinement: RefinementConfig = field(default_factory=RefinementConfig)
    whole_proof: WholeProofConfig = field(default_factory=WholeProofConfig)
    near_miss: NearMissConfig = field(default_factory=NearMissConfig)

    strategies: list[str] = field(default_factory=lambda: ["whole_proof", "stepwise", "refinement"])
    dataset: str = "minif2f"
    output_dir: str = "results/prover"
    cuda_devices: str = ""
    seed: int = 42
    cascade: bool = False
