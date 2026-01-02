#!/bin/bash
# Setup script for kind cluster with Prometheus monitoring

set -e

CLUSTER_NAME="sre-agent-test"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================"
echo "Setting up Kind cluster for SRE Agent MVP"
echo "============================================"

# Check prerequisites
command -v kind >/dev/null 2>&1 || { echo "kind is required but not installed. Aborting."; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required but not installed. Aborting."; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "helm is required but not installed. Aborting."; exit 1; }

# Delete existing cluster if it exists
if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "Deleting existing cluster: ${CLUSTER_NAME}"
    kind delete cluster --name "${CLUSTER_NAME}"
fi

# Create kind cluster
echo ""
echo "Creating Kind cluster..."
kind create cluster --name "${CLUSTER_NAME}" --config "${SCRIPT_DIR}/kind-config.yaml"

# Wait for cluster to be ready
echo "Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# Add Helm repos
echo ""
echo "Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add stable https://charts.helm.sh/stable
helm repo update

# Create monitoring namespace
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

# Install Prometheus stack (includes AlertManager)
echo ""
echo "Installing Prometheus stack..."
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
    --set alertmanager.enabled=true \
    --set grafana.enabled=false \
    --wait --timeout 5m

# Wait for Prometheus to be ready
echo "Waiting for Prometheus to be ready..."
kubectl wait --for=condition=Ready pods -l app.kubernetes.io/name=prometheus -n monitoring --timeout=300s

# Deploy test application
echo ""
echo "Deploying test application..."
kubectl apply -f "${SCRIPT_DIR}/test-app.yaml"

# Wait for test app to be ready
echo "Waiting for test application to be ready..."
kubectl wait --for=condition=Ready pods -l app=nginx-test -n default --timeout=120s

# Deploy alert rules
echo ""
echo "Deploying alert rules..."
kubectl apply -f "${SCRIPT_DIR}/alert-rules.yaml"

# Port forward instructions
echo ""
echo "============================================"
echo "Setup complete!"
echo "============================================"
echo ""
echo "To access services, run these port-forwards in separate terminals:"
echo ""
echo "  Prometheus:    kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090"
echo "  AlertManager:  kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-alertmanager 9093:9093"
echo ""
echo "Then update config.yaml with:"
echo "  prometheus:"
echo "    url: http://localhost:9090"
echo "    alertmanager_url: http://localhost:9093"
echo ""
echo "To inject faults, run:"
echo "  ${SCRIPT_DIR}/inject-fault.sh <fault-type>"
echo ""
echo "Available fault types: pod-crash, scale-zero, bad-image"
