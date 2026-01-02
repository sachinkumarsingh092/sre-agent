# SRE Agent MVP

Lightweight Kubernetes SRE Agent for incident diagnosis and mitigation using local vLLM.

## Features

- **Local LLM**: Uses vLLM with openai/gpt-oss-120b (no external API dependencies)
- **Kubernetes Operations**: Pod-level diagnosis and mitigation with rollback support
- **Prometheus Integration**: Alert detection and metric queries
- **Fail-Fast**: Validates all connections on startup
- **JSON Persistence**: Full incident timeline and state tracking
- **Retry with Reflection**: Learns from failed attempts

## Quick Start

### Prerequisites

1. **vLLM** running locally with openai/gpt-oss-120b:
   ```bash
   vllm serve openai/gpt-oss-120b --gpu-memory-utilization 0.95   --enforce-eager   --max-model-len 16384
   ```

2. **Kubernetes cluster** (kind, minikube, or remote) with kubeconfig

3. **Prometheus + AlertManager** accessible

### Installation

```bash
cd sre-agent-mvp
pip install -e .
```

### Configuration

Edit `config.yaml` to match your environment:

```yaml
llm:
  base_url: "http://localhost:8000/v1"
  model: "openai/gpt-oss-120b"

kubernetes:
  kubeconfig: "~/.kube/config"
  namespace: "default"

prometheus:
  url: "http://localhost:9090"
  alertmanager_url: "http://localhost:9093"

agent:
  max_retries: 3
  retry_sleep_seconds: 30
  validation_wait_seconds: 15
  output_directory: "./output"
```

### Running

```bash
# Full mitigation mode (diagnosis + fix)
sre-agent

# Diagnosis only (no changes made)
sre-agent --diagnosis-only

# With custom config
sre-agent -c /path/to/config.yaml

# Verbose mode
sre-agent -v

# Single run (don't loop)
sre-agent --once

# Skip connection validation (for testing)
sre-agent --skip-validation
```

## Architecture

```
┌─────────────────┐     ┌──────────────────────────────────┐
│   AlertManager  │────▶│          SRE Agent               │
└─────────────────┘     │  ┌────────────┐ ┌─────────────┐  │
                        │  │  Diagnosis │→│  Mitigation │  │
                        │  └────────────┘ └─────────────┘  │
                        │         │              │         │
                        │         ▼              ▼         │
                        │  ┌────────────────────────────┐  │
                        │  │     Validation + Retry     │  │
                        │  └────────────────────────────┘  │
                        └──────────────┬───────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────┐
        │                              │                      │
        ▼                              ▼                      ▼
┌───────────────┐            ┌─────────────────┐    ┌────────────────┐
│  Prometheus   │            │   Kubernetes    │    │     vLLM       │
│   (metrics)   │            │   (kubectl)     │    │ (Qwen2.5-7B)   │
└───────────────┘            └─────────────────┘    └────────────────┘
```

## Incident Lifecycle

1. **Alert Detection**: Fetch active alerts from AlertManager
2. **Diagnosis**: Query metrics/pods, analyze with LLM
3. **Mitigation**: Execute pod-level actions (restart, scale)
4. **Validation**: Check if alerts cleared using oracles
5. **Retry**: If failed, reflect on attempt and retry (max 3 times)

## Testing with Kind

Set up a local test environment with kind:

```bash
# Create cluster with Prometheus
./tests/kind/setup-cluster.sh

# Port forward services (in separate terminals)
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-alertmanager 9093:9093

# Inject faults to test
./tests/kind/inject-fault.sh pod-crash    # Delete a pod
./tests/kind/inject-fault.sh scale-zero   # Scale to 0
./tests/kind/inject-fault.sh restore      # Fix deployment

# Run end-to-end tests
./tests/kind/run-e2e-test.sh

# Cleanup
./tests/kind/cleanup.sh
```

## Output

Incidents are saved to `output/incident_<id>.json`:

```json
{
  "id": "abc123",
  "alert": { "name": "PodCrashLooping", ... },
  "status": "resolved",
  "timeline": [
    { "timestamp": "...", "action_type": "kubectl_get", "description": "..." },
    ...
  ],
  "diagnosis": { "root_cause": "...", ... },
  "actions": [
    { "action_type": "delete", "command": "kubectl delete pod ...", ... }
  ],
  "reflection_history": [],
  "retry_count": 0,
  "created_at": "2024-12-26T...",
  "updated_at": "2024-12-26T..."
}
```

## Project Structure

```
sre-agent-mvp/
├── config.yaml              # Configuration file
├── pyproject.toml           # Project metadata
├── README.md
├── src/
│   └── sre_agent/
│       ├── __init__.py
│       ├── main.py          # Entry point
│       ├── config.py        # Configuration loading
│       ├── models.py        # Data models (Incident, Alert, etc.)
│       ├── logging_config.py
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── diagnosis.py # Diagnosis agent
│       │   └── mitigation.py # Mitigation agent with rollback
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── llm_client.py      # vLLM client
│       │   ├── kube_client.py     # Kubernetes client
│       │   └── prometheus_client.py
│       ├── mitigation/
│       │   ├── __init__.py
│       │   ├── action_stack.py    # Rollback tracking
│       │   └── oracle.py          # Validation oracles
│       └── examples/              # Few-shot prompts
│           ├── kubectl.txt
│           └── prometheus.txt
└── tests/
    └── kind/                # Kind cluster test environment
        ├── setup-cluster.sh
        ├── inject-fault.sh
        ├── run-e2e-test.sh
        └── ...
```

## Compared to stratus-agent

This MVP is a simplified version of stratus-agent:

| Feature | stratus-agent | sre-agent-mvp |
|---------|--------------|---------------|
| LLM Backend | LiteLLM (multi-provider) | vLLM only |
| Agent Framework | CrewAI (multi-agent) | Custom (single agent) |
| Observability | Prometheus, Loki, Jaeger | Prometheus only |
| Operations | Full kubectl + services | Pod operations only |
| Benchmarking | AIOpsLab integration | None (standalone) |
| Dependencies | ~20 packages | ~5 packages |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/
ruff check src/
```
