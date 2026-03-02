"""Configuration loading with fail-fast validation."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class LLMConfig:
    """LLM/vLLM endpoint configuration."""

    base_url: str = "http://localhost:8000/v1"
    model: str = "mistralai/Magistral-Small-2507"
    temperature: float = 0.1
    max_tokens: int = 4096
    # Reasoning model support
    is_reasoning_model: bool = False  # Set to true for o1/gpt-oss style models
    reasoning_effort: Optional[str] = None  # low, medium, high (for models that support it)


@dataclass
class KubernetesConfig:
    """Kubernetes connection configuration."""

    kubeconfig: str = "/Users/sachinsingh/dev/sachinkumarsingh092/sre-agent/sre-agent-mvp/k8s/custom-kubeconfig.yaml"
    namespace: str = "default"

    def __post_init__(self):
        # Expand ~ to home directory
        self.kubeconfig = os.path.expanduser(self.kubeconfig)


@dataclass
class PrometheusConfig:
    """Prometheus and AlertManager configuration."""

    url: str = "http://localhost:9090"
    alertmanager_url: str = "http://localhost:9093"


@dataclass
class AgentConfig:
    """Agent behavior configuration."""

    max_retries: int = 3
    retry_sleep_seconds: int = 30
    validation_wait_seconds: int = 15
    output_directory: str = "./output"

    def __post_init__(self):
        # Create output directory if it doesn't exist
        Path(self.output_directory).mkdir(parents=True, exist_ok=True)


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class Config:
    """Main configuration container."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    kubernetes: KubernetesConfig = field(default_factory=KubernetesConfig)
    prometheus: PrometheusConfig = field(default_factory=PrometheusConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from YAML file.
    
    Fail-fast: exits immediately if config is invalid or required files don't exist.
    
    Args:
        config_path: Path to config.yaml. If None, looks for config.yaml in current directory.
        
    Returns:
        Config object with all settings.
    """
    if config_path is None:
        config_path = "config.yaml"

    config_file = Path(config_path)
    if not config_file.exists():
        print(f"ERROR: Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_file, "r") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML in configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    if raw_config is None:
        raw_config = {}

    # Build config objects from raw YAML
    try:
        config = Config(
            llm=LLMConfig(**raw_config.get("llm", {})),
            kubernetes=KubernetesConfig(**raw_config.get("kubernetes", {})),
            prometheus=PrometheusConfig(**raw_config.get("prometheus", {})),
            agent=AgentConfig(**raw_config.get("agent", {})),
            logging=LoggingConfig(**raw_config.get("logging", {})),
        )
    except TypeError as e:
        print(f"ERROR: Invalid configuration structure: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate kubeconfig exists
    if not Path(config.kubernetes.kubeconfig).exists():
        print(
            f"ERROR: Kubeconfig file not found: {config.kubernetes.kubeconfig}",
            file=sys.stderr,
        )
        sys.exit(1)

    return config


def validate_connections(config: Config) -> None:
    """
    Validate that we can connect to required services.
    
    Fail-fast: exits immediately if any connection fails.
    
    Args:
        config: Configuration object.
    """
    import requests
    from kubernetes import client, config as k8s_config

    # Check Kubernetes connection
    try:
        k8s_config.load_kube_config(config_file=config.kubernetes.kubeconfig)
        v1 = client.CoreV1Api()
        v1.list_namespace(limit=1)
        print("✓ Kubernetes connection successful")
    except Exception as e:
        print(f"ERROR: Cannot connect to Kubernetes cluster: {e}", file=sys.stderr)
        sys.exit(1)

    # Check Prometheus connection
    try:
        response = requests.get(f"{config.prometheus.url}/-/healthy", timeout=5)
        if response.status_code == 200:
            print("✓ Prometheus connection successful")
        else:
            print(
                f"ERROR: Prometheus health check failed: {response.status_code}",
                file=sys.stderr,
            )
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Cannot connect to Prometheus: {e}", file=sys.stderr)
        sys.exit(1)

    # Check AlertManager connection
    try:
        response = requests.get(f"{config.prometheus.alertmanager_url}/-/healthy", timeout=5)
        if response.status_code == 200:
            print("✓ AlertManager connection successful")
        else:
            print(
                f"ERROR: AlertManager health check failed: {response.status_code}",
                file=sys.stderr,
            )
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Cannot connect to AlertManager: {e}", file=sys.stderr)
        sys.exit(1)

    # Check vLLM connection
    try:
        response = requests.get(f"{config.llm.base_url}/models", timeout=10)
        if response.status_code == 200:
            print("✓ vLLM connection successful")
        else:
            print(
                f"ERROR: vLLM health check failed: {response.status_code}",
                file=sys.stderr,
            )
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Cannot connect to vLLM: {e}", file=sys.stderr)
        sys.exit(1)
