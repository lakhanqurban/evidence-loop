from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "model": "glm-5.3-flash-free",
        "max_attempts": 2,
        "max_input_tokens": 12000,
        "max_output_tokens": 2500,
    },
    "execution": {
        "timeout_seconds": 60,
        "max_memory_mb": 2048,
    },
    "generation": {
        "max_tests_per_task": 3,
        "refinement_rounds": 1,
    },
    "budget": {
        "max_cost_per_task_usd": 0.20,
    },
}


@dataclass
class LLMConfig:
    model: str = "glm-5.3-flash-free"
    max_attempts: int = 2
    max_input_tokens: int = 12000
    max_output_tokens: int = 2500


@dataclass
class ExecutionConfig:
    timeout_seconds: int = 60
    max_memory_mb: int = 2048


@dataclass
class GenerationConfig:
    max_tests_per_task: int = 3
    refinement_rounds: int = 1


@dataclass
class BudgetConfig:
    max_cost_per_task_usd: float = 0.20


@dataclass
class Settings:
    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)


def load_config(config_path: str | Path | None = None) -> Settings:
    """Load configuration from YAML if available, otherwise use defaults."""
    config_data = DEFAULT_CONFIG.copy()
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            if yaml is None:
                raise RuntimeError("PyYAML is required to parse config files.")
            with path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
            if isinstance(loaded, dict):
                config_data = _deep_merge(config_data, loaded)

    llm_cfg = config_data.get("llm", {})
    exec_cfg = config_data.get("execution", {})
    gen_cfg = config_data.get("generation", {})
    budget_cfg = config_data.get("budget", {})

    return Settings(
        llm=LLMConfig(**llm_cfg),
        execution=ExecutionConfig(**exec_cfg),
        generation=GenerationConfig(**gen_cfg),
        budget=BudgetConfig(**budget_cfg),
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
