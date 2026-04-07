"""
Model wrapper for vLLM-based inference.
Supports both batch generation (for whole-proof) and single-query generation (for stepwise).
"""
import os
import re
from typing import Optional

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

from .config import ModelConfig


class ProverModel:
    """Wraps a vLLM model for proof generation."""

    def __init__(self, config: Optional[ModelConfig] = None, cuda_devices: str = ""):
        self.config = config or ModelConfig()
        self._model: Optional[LLM] = None
        self._tokenizer = None
        self._cuda_devices = cuda_devices

    def load(self):
        if self._cuda_devices:
            os.environ["CUDA_VISIBLE_DEVICES"] = self._cuda_devices
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.config.model_path, trust_remote_code=True
        )
        self._model = LLM(
            model=self.config.model_path,
            trust_remote_code=True,
            max_model_len=self.config.max_model_len,
            tensor_parallel_size=self.config.tensor_parallel_size,
            gpu_memory_utilization=self.config.gpu_memory_utilization,
        )

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _make_sampling_params(self, n: int = 1, temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None) -> SamplingParams:
        return SamplingParams(
            temperature=temperature or self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            top_p=self.config.top_p,
            n=n,
        )

    def _apply_chat_template(self, messages: list[dict]) -> str:
        return self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    def generate_batch(
        self, prompts: list[str], n: int = 1,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        chat: bool = True,
    ) -> list[list[str]]:
        """Generate completions for a batch of prompts. Returns list of list of outputs."""
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call .load() first.")

        if chat:
            formatted = [
                self._apply_chat_template([{"role": "user", "content": p}])
                for p in prompts
            ]
        else:
            formatted = prompts

        params = self._make_sampling_params(n=n, temperature=temperature, max_tokens=max_tokens)
        outputs = self._model.generate(formatted, params)
        return [[o.text for o in out.outputs] for out in outputs]

    def generate_single(
        self, prompt: str, n: int = 1,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        chat: bool = True,
    ) -> list[str]:
        """Generate completions for a single prompt."""
        results = self.generate_batch(
            [prompt], n=n, temperature=temperature, max_tokens=max_tokens, chat=chat
        )
        return results[0] if results else []

    @staticmethod
    def extract_lean_code(text: str) -> Optional[str]:
        """Extract Lean 4 code from model output (handles ```lean4 blocks and raw output)."""
        patterns = [
            r"```lean4?\s*\n(.*?)```",
            r"```\s*\n(.*?)```",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.DOTALL)
            if m:
                return m.group(1).strip()
        text_stripped = text.strip()
        if text_stripped and not text_stripped.startswith("```"):
            return text_stripped
        return None

    @staticmethod
    def extract_single_tactic(text: str) -> Optional[str]:
        """Extract a single tactic from model output."""
        code = ProverModel.extract_lean_code(text)
        if code is None:
            code = text.strip()
        lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("--")]
        return lines[0] if lines else None
