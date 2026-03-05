# SRE Agent

Lightweight Kubernetes SRE Agent for incident diagnosis and mitigation.

## Features

- **Kubernetes Operations**: Pod-level diagnosis and mitigation with rollback support
- **Prometheus Integration**: Alert detection and metric queries
- **JSON Persistence**: Full incident timeline and state tracking
- **Retry with Reflection**: Learns from failed attempts
- **Transactional No-Regression (TNR)**:  a formal safety specification designed to prevent autonomous SRE agents from making a failing system worse while attempting to fix it. It addresses the critical risk that an agent’s mitigation plan might inadvertently escalate a minor failure into a major outage.

## Quick Start

### Prerequisites

1. **Kubernetes cluster**

2. **Prometheus + AlertManager** (more integrations in the roadmap)

3. (optional) **vLLM** running locally with a reasoning model like openai/gpt-oss-120b:
   ```bash
   $ uv pip install vllm==0.10.1   --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
   $ apt-get install python3-dev
   $ vllm serve openai/gpt-oss-120b --gpu-memory-utilization 0.95   --enforce-eager   --max-model-len 16384
   ```

### Installation

```bash
uv pip install -e .
```

### Configuration

Edit `config.yaml` to match your environment:

```yaml
llm:
  base_url: "http://<vm-ip>:8000/v1"
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

# Process alerts and exit after 2 idle checks (about 1 minute)
sre-agent --exit-on-idle 2
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
│   (metrics)   │            │   (kubectl)     │    │                │
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

## Citations

TNR was inspired by the work performed in this paper:

```
@inproceedings{chen2025stratus,
  title={STRATUS: A Multi-agent System for Autonomous Reliability Engineering of Modern Clouds},
  author={Chen, Yinfang and Pan, Jiaqi and Clark, Jackson and Su, Yiming and Zheutlin, Noah and Bhavya, Bhavya and Arora, Rohan and Deng, Yu and Jha, Saurabh and Xu, Tianyin},
  booktitle={Advances in Neural Information Processing Systems (NeurIPS)},
  year={2025}
}
```
