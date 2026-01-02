"""Few-shot examples for LLM prompts."""

import os
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).parent


def load_example(name: str) -> str:
    """
    Load an example file by name.
    
    Args:
        name: Example file name without extension (e.g., 'kubectl', 'prometheus').
        
    Returns:
        Contents of the example file.
    """
    filepath = _EXAMPLES_DIR / f"{name}.txt"
    if not filepath.exists():
        raise FileNotFoundError(f"Example file not found: {filepath}")
    
    with open(filepath, "r") as f:
        return f.read()


def get_kubectl_examples() -> str:
    """Get kubectl in-context examples."""
    return load_example("kubectl")


def get_prometheus_examples() -> str:
    """Get Prometheus/PromQL in-context examples."""
    return load_example("prometheus")


def get_kubectl_usage_hints() -> str:
    """Get kubectl usage hints."""
    return load_example("how_to_use_kubectl")


def get_metrics_usage_hints() -> str:
    """Get metrics usage hints."""
    return load_example("how_to_use_metrics")
