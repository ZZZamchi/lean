"""
Unified dataset loader for multiple Lean 4 benchmarks.
Supports: miniF2F, Putnam, FATE, ProofNet.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Problem:
    problem_id: str
    name: str
    lean4_code: str
    formal_statement: str
    theorem_header: str
    informal_statement: str = ""
    split: str = "test"
    source: str = ""
    tags: list[str] | None = None


DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"

DATASET_REGISTRY = {
    "minif2f": {"file": "minif2f.jsonl", "format": "jsonl"},
    "minif2f_v2s": {"file": "minif2f_v2s.jsonl", "format": "jsonl"},
    "minif2f_v2c": {"file": "minif2f_v2c.jsonl", "format": "jsonl"},
    "minif2f_v2s_changed": {"file": "minif2f_v2s_changed.jsonl", "format": "jsonl"},
    "round3_subgoals": {"file": "round3_subgoals.jsonl", "format": "jsonl"},
    "minif2f_unsolved39": {"file": "minif2f_unsolved39.jsonl", "format": "jsonl"},
    "minif2f_nearmiss17": {"file": "minif2f_nearmiss17.jsonl", "format": "jsonl"},
    "putnambench": {"file": "putnambench.jsonl", "format": "jsonl"},
    "proofnet": {"file": "proofnet.jsonl", "format": "jsonl"},
    "proofnet_test": {"file": "proofnet_test.jsonl", "format": "jsonl"},
    "fate_h": {"file": "fate_FATE-H.jsonl", "format": "jsonl"},
    "fate_m": {"file": "fate_FATE-M.json", "format": "json"},
    "fate_x": {"file": "fate_FATE-X.json", "format": "json"},
}


def _strip_lean_preamble(code: str) -> str:
    """Remove import/set_option/open lines that the REPL env already provides."""
    lines = code.splitlines()
    result = []
    for line in lines:
        s = line.strip()
        if s.startswith("import ") or s.startswith("set_option ") or s.startswith("open "):
            continue
        if not s:
            continue
        result.append(line)
    return "\n".join(result)


def _extract_header(lean4_code: str) -> str:
    stripped = _strip_lean_preamble(lean4_code)
    parts = stripped.split(":= by")
    if len(parts) >= 2:
        return parts[0].strip() + " := by"
    parts = stripped.split(":=")
    if len(parts) >= 2:
        return parts[0].strip() + " :="
    return stripped


def _parse_record(d: dict, source: str) -> Problem:
    # FATE-M / FATE-X store Lean only in formal_statement; Putnam/miniF2F use lean4_code.
    lean4_code = (d.get("lean4_code") or "").strip() or (d.get("formal_statement") or "")
    pid = d.get("problem_id") or d.get("name")
    if not pid and d.get("id") is not None:
        src = d.get("source", source)
        pid = f"{src}_{d['id']}"
    return Problem(
        problem_id=pid or "",
        name=d.get("name", pid or ""),
        lean4_code=lean4_code,
        formal_statement=d.get("formal_statement") or _extract_header(lean4_code),
        theorem_header=_extract_header(lean4_code),
        informal_statement=d.get("informal_prefix", d.get("informal_statement", "")),
        split=d.get("split", "test"),
        source=source,
        tags=d.get("tag"),
    )


def load_dataset(
    name: str,
    split: Optional[str] = None,
    dataset_dir: Optional[str] = None,
    limit: Optional[int] = None,
    shard_id: int = 0,
    num_shards: int = 1,
) -> list[Problem]:
    """
    Load a benchmark dataset by name.

    Args:
        name: Dataset name (e.g., "minif2f", "putnambench", "fate_h")
        split: Filter by split ("valid", "test", or None for all)
        dataset_dir: Override default dataset directory
        limit: Max number of problems to load

    Returns:
        List of Problem objects
    """
    base_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR

    if name not in DATASET_REGISTRY:
        path = base_dir / name
        if path.suffix == ".jsonl":
            fmt = "jsonl"
        elif path.suffix == ".json":
            fmt = "json"
        else:
            raise ValueError(f"Unknown dataset: {name}. Available: {list(DATASET_REGISTRY.keys())}")
        file_path = path
    else:
        info = DATASET_REGISTRY[name]
        file_path = base_dir / info["file"]
        fmt = info["format"]

    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    if fmt == "jsonl":
        with open(file_path) as f:
            records = [json.loads(line) for line in f if line.strip()]
    else:
        with open(file_path) as f:
            records = json.load(f)
            if isinstance(records, dict):
                records = list(records.values())

    problems = [_parse_record(d, name) for d in records]

    if split:
        problems = [p for p in problems if p.split == split]

    if num_shards > 1:
        problems = [p for i, p in enumerate(problems) if i % num_shards == shard_id]

    if limit:
        problems = problems[:limit]

    return problems


def list_datasets() -> list[str]:
    return list(DATASET_REGISTRY.keys())
